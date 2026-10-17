"""Prepare a NEW protected asynchronous RL run from BC; never opens robot output."""
import argparse
from dataclasses import replace
import json
from pathlib import Path

import torch

from .config import HILConfig
from .exchange import atomic_json, publish, read_episode
from .networks import SAC
from .periodic_bc_label import validate_bc_label
from omi_hil_rl.training.eef_bc_data import sha256
from omi_hil_rl.training.dual_replay import DualTransitionReplay, VERSION as REPLAY_VERSION


def prepare(bc_run, run, *, capacity=4000, intervention_capacity=2000, warmup=1000, bc_weight=10., actor_lr=1e-5, device='cpu',
            replay_backend='disk', cache_target_gib=16., cache_limit_gib=20., recorded_sources=(), weights_only=False,
            episode_seconds=None, train_tactile_encoder=False, train_fusion_layer=False,
            encoder_learning_rate=1e-5, max_total_episodes=None, critic_learning_rate=3e-4,
            discount=.98, target_tau=.005, critic_actor_ratio=2, image_augmentation=True):
    bc_run, run = Path(bc_run).resolve(), Path(run).resolve()
    if run.exists():
        raise ValueError('use a new RL run; existing BC/RL runs are never overwritten')
    if weights_only and (replay_backend != 'cached' or recorded_sources):
        raise ValueError('weights-only requires cached replay and no recorded sources')
    if max_total_episodes is not None and (type(max_total_episodes) is not int or max_total_episodes < 1):
        raise ValueError('max total episodes must be a positive integer')
    state = torch.load(bc_run/'actor.pt', map_location='cpu', weights_only=True)
    if state.get('training_method') != 'behavior_cloning':
        raise ValueError('a behavior-cloning checkpoint is required')
    config = HILConfig(**json.loads((bc_run/'config.json').read_text()))
    if state['contract'] != config.replay_contract():
        raise ValueError('BC config/contract mismatch')
    source_episode_seconds = config.episode_seconds
    if episode_seconds is not None:
        if recorded_sources:
            raise ValueError('episode duration override cannot import additional recorded sources')
        config = replace(config, episode_seconds=episode_seconds)
    contract = config.replay_contract()
    # Never read the historical data index in weights-only mode.
    dataset = (dict(episodes=[], training_data_policy='new_session_only') if weights_only
               else json.loads((bc_run/'dataset.json').read_text()))
    entries = [e for e in dataset['episodes'] if e.get('split') == 'training']
    if (not entries and not weights_only) or min(capacity, intervention_capacity) < 1:
        raise ValueError('training samples and positive capacities required')
    if len({e['manifest']['episode'] for e in entries}) != len(entries):
        raise ValueError('duplicate seed episode')
    agent = SAC(state['recipe'], contract, device=device, freeze_encoder=True,
                critic_warmup_updates=warmup, bc_weight=bc_weight, actor_learning_rate=actor_lr,
                train_tactile_encoder=train_tactile_encoder, train_fusion_layer=train_fusion_layer,
                encoder_learning_rate=encoder_learning_rate, learning_rate=critic_learning_rate,
                gamma=discount, tau=target_tau, critic_actor_ratio=critic_actor_ratio,
                image_augmentation=image_augmentation)
    # Explicit new-run transfer: only the episode duration may differ. The
    # inherited tensors/recipe remain exact; all new artifacts use one contract.
    agent.initialize_bc(dict(state, contract=contract), provenance=dict(
        path=str(bc_run/'actor.pt'), sha256=sha256(bc_run/'actor.pt'), bc_version=state['updates'],
        source_contract=state['contract']))
    # Bitwise parameter identity, including normalizer buffers, before any RL updates.
    for key, value in state['actor'].items():
        if not torch.equal(agent.actor.state_dict()[key].cpu(), value):
            raise ValueError('BC transfer changed actor parameters: '+key)
    run.mkdir(parents=True)
    protection = ('frozen_visual_selective_encoder_after_critic_warmup_bc_anchor' if train_tactile_encoder or train_fusion_layer
                  else 'frozen_encoder_critic_warmup_bc_anchor')
    atomic_json(run/'initializing.json', dict(bc=str(bc_run), protection=protection))
    if replay_backend not in ('disk', 'cached'):
        raise ValueError('unknown replay backend')
    if replay_backend == 'cached':
        from omi_hil_rl.training.cached_replay import CachedDualReplay, VERSION as backend_version, GIB
        replay = CachedDualReplay(run/'replay', config.replay_contract(),
            cache_bytes=int(cache_target_gib*GIB), memory_limit_bytes=int(cache_limit_gib*GIB),
            sources=recorded_sources)
    else:
        if recorded_sources:
            raise ValueError('--recorded-source requires cached replay')
        backend_version = REPLAY_VERSION
        replay = DualTransitionReplay(run/'replay', config.replay_contract(),
            seed_capacity=sum(e['manifest']['count'] for e in entries),
            online_capacity=capacity, intervention_capacity=intervention_capacity)
    count = 0
    try:
        for entry in entries:
            path, manifest = Path(entry['path']), entry['manifest']
            if manifest['contract'] != state['contract'] or not manifest['keep']:
                raise ValueError('seed contract/outcome mismatch')
            if sha256(path/'ready.json') != entry['manifest_sha256']:
                raise ValueError('seed manifest changed')
            hashes = entry['sample_sha256']
            if len(hashes) != manifest['count']:
                raise ValueError('incomplete seed hash list')
            if replay_backend == 'cached':
                count += replay.register_episode(path/'ready.json', seed=True, expected_hashes=hashes,
                    allow_seed_horizon_change=config.episode_seconds != source_episode_seconds)
                continue
            for record in read_episode(path, manifest):
                if sha256(path/f"{record['step']:06d}.npz") != hashes[record['step']]:
                    raise ValueError('seed sample changed')
                # Seed import reads the BC training index. Keep periodic label
                # checks scoped to that BC data path; runtime replay rules stay
                # unchanged.
                validate_bc_label(config.replay_contract(), record['executed_action'], record)
                if record['action_source'] != 'human':
                    raise ValueError('BC anchor seed must contain human actions')
                if config.episode_seconds != source_episode_seconds:
                    record['seed_horizon_transfer'] = dict(source_episode_seconds=source_episode_seconds,
                                                           target_episode_seconds=config.episode_seconds)
                replay.append_seed(record, origin=manifest['origin'])
                count += 1
        replay.seal_seed()
        streams = replay.buffer.stream_counts()
        if replay_backend == 'cached':
            streams = dict(online=0, demonstration=count, initial_demonstration=count,
                           intervention=0, offline_demonstration=count)
    finally:
        replay.close()
    atomic_json(run/'config.json', contract['config'])
    atomic_json(run/'recipe.json', state['recipe'])
    atomic_json(run/'dataset.json', dict(dataset, episodes=entries))
    publish(run, agent)
    report = dict(samples=count, episodes=len(entries), streams=streams,
                  initial_actor_exact=True, bc_version=state['updates'], rl_version=0,
                  critic_warmup_updates=warmup, bc_weight=bc_weight, actor_learning_rate=actor_lr,
                  encoder_frozen=not (train_tactile_encoder or train_fusion_layer),
                  train_tactile_encoder=train_tactile_encoder,
                  train_fusion_layer=train_fusion_layer, encoder_learning_rate=encoder_learning_rate,
                  visual_encoder_frozen=True, fusion_layer_frozen=not train_fusion_layer,
                  critic_learning_rate=critic_learning_rate, discount=discount, target_tau=target_tau,
                  critic_actor_ratio=critic_actor_ratio, image_augmentation=image_augmentation,
                  tactile_unfreeze_after_updates=warmup if train_tactile_encoder else None,
                  encoder_freeze_policy=protection,
                  historical_seed_is_not_new_robot_experience=True,
                  weights_only=weights_only,
                  episode_seconds=config.episode_seconds, source_episode_seconds=source_episode_seconds,
                  max_total_episodes=max_total_episodes,
                  replay_backend=backend_version)
    atomic_json(run/'bc_initialization.json', report)
    # This marker is last: a failed preparation cannot be launched as a session.
    atomic_json(run/'async_session.json', dict(mode='async_hil_v1', seed=str(bc_run),
        contract=config.replay_contract(), control_mode='periodic_training_v1',
        reset_actions_in_replay=False, policy_selection='latest_validated_not_best', replay_capacity=capacity,
        replay_backend=backend_version, intervention_capacity=intervention_capacity,
        max_total_episodes=max_total_episodes,
        training_data_policy='new_session_only' if weights_only else 'bc_seed_and_online'))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bc-run', type=Path, required=True)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--capacity', type=int, default=4000)
    p.add_argument('--intervention-capacity', type=int, default=2000)
    p.add_argument('--critic-warmup-updates', type=int, default=1000)
    p.add_argument('--bc-weight', type=float, default=10.)
    p.add_argument('--actor-learning-rate', type=float, default=1e-5)
    p.add_argument('--critic-learning-rate', type=float, default=3e-4)
    p.add_argument('--discount', type=float, default=.98)
    p.add_argument('--target-tau', type=float, default=.005)
    p.add_argument('--critic-actor-ratio', type=int, default=2)
    p.add_argument('--image-augmentation', action=argparse.BooleanOptionalAction, default=True)
    p.add_argument('--train-tactile-encoder', action='store_true',
                   help='After critic warmup, train shared tactile CNN via critic; visual stays frozen, fusion is a separate option')
    p.add_argument('--train-fusion-layer', action='store_true',
                   help='After critic warmup, also train the shared multimodal fusion projection via critic')
    p.add_argument('--encoder-learning-rate', type=float, default=1e-5)
    p.add_argument('--max-total-episodes', type=int, help='Persistent cap on started online episodes, across restarts')
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    p.add_argument('--replay-backend', choices=['disk', 'cached'], default='disk')
    p.add_argument('--cache-target-gib', type=float, default=16., help='combined resident Demo/RL data budget')
    p.add_argument('--cache-limit-gib', type=float, default=20., help='managed data pipeline limit, not total process RSS')
    p.add_argument('--recorded-source', type=Path, action='append', default=[],
                   help='read-only BC/collection run to index automatically; cached replay only')
    p.add_argument('--weights-only', action='store_true',
                   help='inherit only BC weights; cached Demo/RL start empty, no historical data sources')
    p.add_argument('--episode-seconds', type=float,
                   help='New episode duration; preserves exact BC tensors and original seed labels')
    from .run_settings import parse_settings, save_settings_snapshot
    a = parse_settings(p, 'prepare')
    torch.set_num_threads(2)
    print(json.dumps(prepare(a.bc_run, a.run, capacity=a.capacity, warmup=a.critic_warmup_updates,
                            bc_weight=a.bc_weight, actor_lr=a.actor_learning_rate, device=a.device,
                            intervention_capacity=a.intervention_capacity, replay_backend=a.replay_backend,
                            cache_target_gib=a.cache_target_gib, cache_limit_gib=a.cache_limit_gib,
                            recorded_sources=a.recorded_source, weights_only=a.weights_only,
                            episode_seconds=a.episode_seconds, train_tactile_encoder=a.train_tactile_encoder,
                            train_fusion_layer=a.train_fusion_layer, encoder_learning_rate=a.encoder_learning_rate,
                            max_total_episodes=a.max_total_episodes, critic_learning_rate=a.critic_learning_rate,
                            discount=a.discount, target_tau=a.target_tau, critic_actor_ratio=a.critic_actor_ratio,
                            image_augmentation=a.image_augmentation)), flush=True)
    save_settings_snapshot(a, 'prepare')


if __name__ == '__main__':
    main()
