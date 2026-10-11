#!/usr/bin/env python3
"""Bounded offline BC->SAC iteration with episode-disjoint evaluation.

No ROS, joystick or robot publishers. Source runs stay immutable; all artifacts
and test weights go into a new output directory. Metrics are offline diagnostics,
not claims about autonomous task success.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import random
import sqlite3
import time
from types import SimpleNamespace

import numpy as np
import torch

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.exchange import atomic_json, owner_lock
from omi_hil_rl.hil.learner import run_learner
from omi_hil_rl.hil.networks import SAC, load_actor
from omi_hil_rl.hil.observation_storage import ObservationReader
from omi_hil_rl.hil.prepare_bc_rl import prepare
from omi_hil_rl.hil.shutdown import graceful_stop
from omi_hil_rl.training.cached_replay import digest
from omi_hil_rl.training.replay_sources import periodic_records
from omi_hil_rl.training.transition_replay import TransitionReplay, _spaces


def evaluate(actor, contract, directories, device, *, critic=None):
    validator=TransitionReplay.__new__(TransitionReplay)
    validator.contract=contract
    obs_space,action_space=_spaces(contract)
    validator.buffer=SimpleNamespace(observation_space=obs_space,action_space=action_space)
    pending=[]; predictions=[]; targets=[]; human=[]; ids=[]; q_values=[]; rewards=[]; terminals=[]
    def flush():
        if not pending:
            return
        obs={k:torch.as_tensor(np.stack([r['observation'][k] for r in pending]),device=device)
             for k in pending[0]['observation']}
        labels=np.stack([r['executed_action'] for r in pending])
        with torch.inference_mode():
            prediction=actor.sample(obs,deterministic=True)[0].cpu().numpy()
            if critic is not None:
                q=critic(obs,torch.as_tensor(labels,device=device)).mean(0).cpu().numpy()
                q_values.extend(q.reshape(-1).tolist())
        assert np.isfinite(prediction).all()
        predictions.append(prediction);targets.append(labels)
        human.extend(r['action_source']=='human' for r in pending)
        rewards.extend(r['reward'] for r in pending)
        terminals.extend(r['terminated'] for r in pending)
        ids.extend(f"{r['episode']}:{r['step']}" for r in pending)
        pending.clear()
    for directory in directories:
        summary={}
        reader=ObservationReader(cache_size=16)
        for _,_,record in periodic_records(directory,contract,validator,summary,reader=reader):
            validator.validate(record)
            # Evaluation needs only the pre-action input and recorded label.
            pending.append({k:record[k] for k in ('observation','executed_action','action_source','episode','step',
                                                 'reward','terminated','truncated')})
            if len(pending)==16:
                flush()
        flush()
    pred=np.concatenate(predictions);target=np.concatenate(targets);mask=np.asarray(human,bool)
    if not mask.any():
        raise ValueError('held-out episodes contain no human labels')
    metrics=dict(samples=len(pred),human_samples=int(mask.sum()),
        human_action_mse=float(np.mean((pred[mask]-target[mask])**2)),
        human_mse_per_axis=np.mean((pred[mask]-target[mask])**2,axis=0).tolist(),
        predicted_abs_over_098_per_axis=np.mean(np.abs(pred)>.98,axis=0).tolist())
    if q_values:
        assert np.isfinite(q_values).all()
        metrics['q_recorded_action']=dict(min=float(np.min(q_values)),mean=float(np.mean(q_values)),max=float(np.max(q_values)))
        for name,selection in (('positive',np.asarray(rewards)>0),('terminal',np.asarray(terminals,bool))):
            selected=np.asarray(q_values)[selection]
            metrics['q_recorded_'+name]=dict(count=len(selected),mean=float(selected.mean()) if len(selected) else None)
    return metrics,dict(prediction=pred,target=target,human_mask=mask,sample_ids=np.asarray(ids),
                        rewards=np.asarray(rewards),terminals=np.asarray(terminals),q_recorded=np.asarray(q_values))


def summarize_diagnostics(path):
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    result={}
    for name,group in (('warmup',[r for r in rows if r['demo_only_warmup']]),
                       ('mixed',[r for r in rows if not r['demo_only_warmup']]),
                       ('first_100',rows[:100]),('last_100',rows[-100:])):
        if not group:
            continue
        result[name]=dict(updates=len(group),
            **{key:sum(r[key] for r in group) for key in
               ('batch_samples','positive_reward_count','terminal_count','positive_terminal_count','target_q_negative_count')},
            **{key:float(np.mean([r[key] for r in group])) for key in
               ('q_mean','target_q_mean','bootstrap_q_mean','td_abs_mean','critic_loss')},
            positive_reward_updates=[r['update'] for r in group if r['positive_reward_count']])
    result['positive_batches']=[{k:r.get(k) for k in ('update','positive_reward_count','positive_terminal_count',
                               'positive_q_mean','terminal_target_mean')} for r in rows if r['positive_reward_count']]
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bc-run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--updates',type=int,default=1200)
    p.add_argument('--warmup',type=int,default=1000)
    p.add_argument('--batch-size',type=int,default=2)
    p.add_argument('--cache-target-gib',type=float,default=16.)
    p.add_argument('--cache-limit-gib',type=float,default=20.)
    p.add_argument('--split-seed',type=int,default=11)
    p.add_argument('--device',choices=('cpu','cuda'),default='cuda')
    p.add_argument('--diagnose-q',action='store_true',help='also evaluate initial and warmup-checkpoint Critics')
    args=p.parse_args()
    if args.updates<=args.warmup or args.warmup<0 or args.batch_size<2 or args.batch_size%2:
        p.error('updates must exceed warmup; batch size must be even and >=2')
    if args.diagnose_q and args.warmup%50:
        p.error('diagnostic warmup checkpoint must coincide with publication (multiple of 50)')
    if args.device=='cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable; no experiment directory was created')
    source,output=args.bc_run.resolve(),args.output.resolve()
    if output.exists():
        raise ValueError('use a NEW output directory')
    output.mkdir(parents=True)
    run=output/'run'
    report=dict(status='running',source=str(source),output=str(output),robot_output=False,
                updates_requested=args.updates,warmup=args.warmup,batch_size=args.batch_size,
                gripper_assumption='held_closed; no gripper control or inspection')
    started=time.monotonic()
    torch.set_num_threads(2);torch.manual_seed(7);np.random.seed(7)
    try:
        with owner_lock(source,'actor'):
            if json.loads((source/'bc_state.json').read_text())['phase']!='CLOSED':
                raise ValueError('source BC run must be closed')
            original={str(f.relative_to(source)):digest(f) for f in source.rglob('*') if f.is_file()}
            atomic_json(output/'source_hashes.json',original)
            checkpoints=torch.load(source/'actor.pt',map_location='cpu',weights_only=True)
            contract=checkpoints['contract'];config=HILConfig(**contract['config'])
            episodes=[]
            for audit in sorted(source.glob('periodic_episodes/*/audit.json')):
                value=json.loads(audit.read_text())
                if value.get('observation_storage_version')=='omi-observation-frames-v1' and value['reason'] in ('success','timeout','manual_stop'):
                    episodes.append((audit.parent,value))
            successes=[d for d,a in episodes if a['success']]
            timeouts=[d for d,a in episodes if a['reason']=='timeout']
            if len(successes)<3 or not timeouts:
                raise ValueError('need >=3 successful and >=1 timeout episodes for this stratified experiment')
            rng=random.Random(args.split_seed)
            held=rng.sample(successes,2)+rng.sample(timeouts,1)
            training=[d for d,_ in episodes if d not in held]
            dataset=json.loads((source/'dataset.json').read_text())
            initial_ids={e['manifest']['episode'].rsplit('-segment-',1)[0] for e in dataset['episodes']}
            assert not initial_ids & {d.name for d in held}
            seed_count=sum(e['manifest']['count'] for e in dataset['episodes'] if e.get('split')=='training')
            view=output/'training_source'
            (view/'periodic_episodes').mkdir(parents=True)
            counts=Counter()
            for directory in training:
                (view/'periodic_episodes'/directory.name).symlink_to(directory,target_is_directory=True)
                for path in directory.glob('[0-9]*.npz'):
                    with np.load(path,allow_pickle=False) as archive:
                        meta=json.loads(str(archive['metadata']))
                    if meta['gate'] in ('human','policy'):
                        counts[meta['gate']]+=1
            expected_online=sum(counts.values());expected_demo=seed_count+counts['human']
            split=dict(seed=args.split_seed,training=[d.name for d in training],validation=[d.name for d in held],
                       expected_online=expected_online,expected_demo=expected_demo,initial_demo=seed_count,
                       counts=dict(counts),basis='whole_original_episode; two success and one timeout held out')
            atomic_json(output/'split.json',split);report['split']=split
            print('SPLIT',json.dumps(split),flush=True)
            actor,_,_=load_actor(source/'actor.pt',contract,args.device)
            before,before_arrays=evaluate(actor,contract,held,args.device)
            report['before']=before;np.savez_compressed(output/'evaluation_before.npz',**before_arrays)
            print('BC_BASELINE',json.dumps(before),flush=True)
            del actor
            if args.device=='cuda':torch.cuda.empty_cache()
            report['initialization']=prepare(source,run,replay_backend='cached',
                cache_target_gib=args.cache_target_gib,cache_limit_gib=args.cache_limit_gib,
                recorded_sources=[view],warmup=args.warmup,device='cpu')
            def probe_checkpoint(label):
                # Restoring networks consumes RNG; diagnostic probes must not
                # change training's random crops or sampled actions.
                with torch.random.fork_rng(devices=[torch.cuda.current_device()] if args.device=='cuda' else []):
                    probe=SAC.restore(torch.load(run/'learner.pt',map_location=args.device,weights_only=True),
                                      device=args.device,expected_contract=contract)
                    metrics,arrays=evaluate(probe.actor,contract,held,args.device,critic=probe.critic)
                    metrics['update']=probe.updates
                    atomic_json(output/f'probe_{label}.json',metrics)
                    np.savez_compressed(output/f'probe_{label}.npz',**arrays)
                print('Q_PROBE',label,json.dumps(metrics),flush=True)
                return metrics
            if args.diagnose_q:
                report['initial_q_probe']=probe_checkpoint('initial')
            atomic_json(output/'report.json',report)
            last_update=[-1]
            with (output/'training_progress.jsonl').open('w') as log,graceful_stop() as stop:
                def progress():
                    path=run/'status.json'
                    if path.exists():
                        value=json.loads(path.read_text());update=value.get('update')
                        if update!=last_update[0] and not value.get('waiting'):
                            log.write(json.dumps(value)+'\n');log.flush();last_update[0]=update
                            if args.diagnose_q and update==args.warmup:
                                report['warmup_q_probe']=probe_checkpoint('warmup')
                    return stop()
                # All pre-existing training human data must be resident before
                # offline warmup. Online thresholds ensure full training pool
                # availability before the Actor phase, rather than a lucky prefix.
                result=run_learner(run,config,batch_size=args.batch_size,min_online=expected_online,
                    min_demo=expected_demo,updates=args.updates,publish_every=50,device=args.device,
                    wait_seconds=1200.,should_stop=progress,max_updates_per_transition=1.)
                progress()
            report['training']=result
            report['critic_diagnostics']=summarize_diagnostics(output/'training_progress.jsonl')
            report['telemetry']=json.loads((run/'monitor/learner.json').read_text())
            with sqlite3.connect('file:'+str(run/'replay/catalog.sqlite3')+'?mode=ro',uri=True) as db:
                indexed={row[0].removeprefix('online:') for row in db.execute('SELECT key FROM sources WHERE seed=0')}
                report['reward_catalog']=[dict(seed=bool(seed),human=bool(human),count=count,
                    positive_rewards=positive,terminals=terminal,negative_rewards=negative)
                    for seed,human,count,positive,terminal,negative in db.execute(
                        "SELECT seed,human,COUNT(*),SUM(json_extract(metadata,'$.reward')>0),"
                        "SUM(json_extract(metadata,'$.terminated')),SUM(json_extract(metadata,'$.reward')<0) "
                        "FROM records GROUP BY seed,human")]
            assert indexed=={d.name for d in training} and not indexed & {d.name for d in held}
            report['held_out_not_indexed']=True
            stats=report['telemetry']['replay']
            assert stats['catalog_online']==expected_online
            assert stats['catalog_interventions']==counts['human']
            assert stats['catalog_seed']==seed_count
            assert stats['peak_managed_bytes']<=stats['memory_limit_bytes']
            model=SAC.restore(torch.load(run/'learner.pt',map_location=args.device,weights_only=True),
                              device=args.device,expected_contract=contract)
            after,after_arrays=evaluate(model.actor,contract,held,args.device,critic=model.critic)
            assert np.array_equal(before_arrays['sample_ids'],after_arrays['sample_ids'])
            assert np.array_equal(before_arrays['target'],after_arrays['target'])
            delta=after_arrays['prediction']-before_arrays['prediction']
            after.update(actor_vs_bc_mse=float(np.mean(delta**2)),actor_vs_bc_max_abs=float(np.max(abs(delta))))
            report['after']=after;np.savez_compressed(output/'evaluation_after.npz',**after_arrays)
            print('FINAL_EVALUATION',json.dumps(after),flush=True)
            assert all(torch.equal(v.cpu(),checkpoints['actor'][k]) for k,v in model.actor.state_dict().items() if k.startswith('encoder.'))
            assert all(digest(source/name)==sha for name,sha in original.items())
            report.update(status='completed' if result['updates']==args.updates else 'stopped',
                source_unchanged=True,encoder_unchanged=True,source_files_checked=len(original),
                elapsed_s=time.monotonic()-started,task_success_rate_evaluated=False)
            atomic_json(output/'report.json',report)
            print('EXPERIMENT_DONE',report['status'],report['elapsed_s'],flush=True)
    except BaseException as exc:
        report.update(status='failed',error=repr(exc),elapsed_s=time.monotonic()-started)
        atomic_json(output/'report.json',report)
        raise


if __name__=='__main__':
    main()
