import gc
import json
from pathlib import Path
import time

import numpy as np
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.exchange import EpisodeSpool, read_episode
from omi_hil_rl.training.cached_replay import CachedDualReplay, METADATA_ALLOWANCE
from omi_hil_rl.training.dual_replay import open_replay


def contract():
    c = HILConfig().replay_contract()
    for key in ('rgb', 'wrist_rgb'):
        c['observations'][key]['shape'] = [10, 3, 2, 2]
    c['observations']['tactile']['shape'] = [10, 10, 2, 2]
    return c


def episode(root, name, c, *, sources=('human',), success=True):
    writer = EpisodeSpool(root, name, c)
    obs = {k: np.zeros(s['shape'], dtype=s['dtype']) for k, s in c['observations'].items()}
    obs['history_mask'][:] = 1
    obs['camera_mask'][:] = 1
    obs['state'][:, -1] = 1
    for i, source in enumerate(sources):
        final = i == len(sources)-1
        writer.append(obs, obs, float(final and success), final and success, final and not success,
            dict(episode=name, step=i, observation_time_ns=1_000_000_000+i*100_000_000,
                 next_observation_time_ns=1_100_000_000+i*100_000_000, action_source=source,
                 command_status='fake', executed_action=np.full(6, .1 if source == 'human' else .8, np.float32)))
    return writer.directory/'ready.json', writer.finish(True, reason='success' if success else 'timeout')


def buffer(path, c, slots=8, **kwargs):
    size = 2*sum(int(np.prod(s['shape']))*np.dtype(s['dtype']).itemsize for s in c['observations'].values())+24+8+4096
    return CachedDualReplay(path, c, cache_bytes=slots*size, memory_limit_bytes=64*1024**2,
                            prefetch=False, **kwargs)


def register(replay, path, seed=False):
    count = replay.register_episode(path, seed=seed)
    if seed:
        replay.seal_seed()
    replay.wait_idle()
    return count


def test_shared_intervention_exact_half_sampling_and_no_disk_in_sample(tmp_path, monkeypatch):
    c = contract()
    seed, _ = episode(tmp_path/'data', 'seed', c)
    online, _ = episode(tmp_path/'data', 'online', c, sources=('human', 'policy'))
    r = buffer(tmp_path/'r', c)
    try:
        register(r, seed, True)
        register(r, online)
        assert r.size() == 3
        assert r.stream_counts() == dict(online=2, demonstration=2, initial_demonstration=1,
                                       intervention=1, offline_demonstration=1)
        assert len(r.demo & r.online) == 1  # one physical record, two memberships
        assert r.storage_stats()['resident_bytes'] == 3*r.entry_bytes
        def fail(*a, **kw):
            raise AssertionError('sample touched a file')
        monkeypatch.setattr(np, 'load', fail)
        draws = r.sample(20).actions.numpy()[:, 0]
        assert np.count_nonzero(draws < .5) >= 10
        assert (r.sample_human(20).actions.numpy() < .5).all()
        with pytest.raises(ValueError, match='even'):
            r.sample(3)
    finally:
        r.close()


def test_two_disjoint_streams_sample_exactly_half(tmp_path):
    c = contract()
    seed, _ = episode(tmp_path/'data', 'seed', c)
    online, _ = episode(tmp_path/'data', 'online', c, sources=('policy',))
    r = buffer(tmp_path/'r', c)
    try:
        register(r, seed, True)
        with pytest.raises(RuntimeError, match='empty'):
            r.sample(4)
        register(r, online)
        a = r.sample(100).actions.numpy()[:, 0]
        assert np.count_nonzero(a < .5) == 50
        assert np.count_nonzero(a > .5) == 50
    finally:
        r.close()


def test_bounded_working_set_retains_seed_and_catalog_reloads_history(tmp_path):
    c = contract()
    seed, _ = episode(tmp_path/'data', 'seed', c)
    online, _ = episode(tmp_path/'data', 'online', c, sources=tuple(['human', 'policy']*10))
    r = buffer(tmp_path/'r', c, slots=6, turnover_fraction=1.)
    try:
        register(r, seed, True)
        register(r, online)
        initial = set(r.cache)
        seen = set(initial)
        for _ in range(8):
            r.refresh(); r.wait_idle()
            assert len(r.cache) <= 6 and r.seeds <= r.cache.keys()
            assert r.stream_counts()['initial_demonstration'] == 1
            seen.update(r.cache)
        assert len(seen) > len(initial)
        assert r.storage_stats()['catalog_online'] == 20
        assert r.storage_stats()['peak_managed_bytes'] <= r.memory_limit_bytes
        assert online.exists()
    finally:
        r.close()


def test_batch_memory_is_reserved_before_allocation_and_released(tmp_path):
    c = contract()
    seed, _ = episode(tmp_path/'data', 'seed', c)
    online, _ = episode(tmp_path/'data', 'online', c, sources=('policy',))
    r = buffer(tmp_path/'r', c)
    try:
        register(r, seed, True); register(r, online)
        baseline = r.storage_stats()['managed_bytes']
        b = r.sample(4)
        assert r.storage_stats()['batch_bytes'] == 4*r.payload_bytes
        # A retained tensor view keeps its array reservation alive.
        view = b.observations['rgb'][0]
        del b
        gc.collect()
        assert r.storage_stats()['batch_bytes'] > 0
        del view
        gc.collect()
        assert r.storage_stats()['batch_bytes'] == 0
        with pytest.raises(MemoryError):
            r.sample(2*(r.memory_limit_bytes//r.payload_bytes))
        assert r.storage_stats()['managed_bytes'] == baseline
    finally:
        r.close()


def test_sqlite_registration_reopen_duplicate_and_changed_source(tmp_path):
    c = contract()
    seed, _ = episode(tmp_path/'data', 'seed', c)
    online, _ = episode(tmp_path/'data', 'online', c, sources=('human', 'policy'))
    r = buffer(tmp_path/'r', c)
    register(r, seed, True); register(r, online)
    with pytest.raises(RuntimeError, match='writer'):
        open_replay(tmp_path/'r')
    r.close()
    r = CachedDualReplay.reopen(tmp_path/'r', prefetch=False)
    try:
        r.wait_idle()
        assert r.register_episode(online) == 0
        assert r.stream_counts()['online'] == 2
        changed = json.loads(online.read_text()); changed['reason'] = 'changed'
        online.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match='changed source'):
            r.register_episode(online)
    finally:
        r.close()


def test_rejected_episode_is_atomic_and_incomplete_is_not_discovered(tmp_path):
    c = contract()
    path, m = episode(tmp_path/'data', 'bad', c, sources=('human', 'policy'))
    f = path.parent/'000001.npz'
    with np.load(f) as z:
        arrays = {k:z[k].copy() for k in z.files}
    arrays['observation__state'][0, 0] = np.nan
    np.savez_compressed(f, **arrays)
    r = buffer(tmp_path/'r', c)
    try:
        with pytest.raises(ValueError, match='nonfinite'):
            r.register_episode(path)
        assert r.storage_stats()['catalog_online'] == 0
        assert r.db.execute('SELECT COUNT(*) FROM sources').fetchone()[0] == 0
    finally:
        r.close()
    r = CachedDualReplay.reopen(tmp_path/'r', prefetch=False)
    try:
        assert r.storage_stats()['catalog_online'] == 0
    finally:
        r.close()


def test_async_discovery_and_prefetch_are_shutdown_cleanly(tmp_path):
    c = contract()
    seed, _ = episode(tmp_path/'seed', 'seed', c)
    online, _ = episode(tmp_path/'data', 'online', c, sources=('policy',)*4)
    r = buffer(tmp_path/'r', c, sources=[tmp_path/'data'])
    register(r, seed, True)
    before = online.read_bytes()
    assert r.import_ready(tmp_path/'empty') == 0
    r.wait_idle()
    assert r.import_ready(tmp_path/'empty') == 4
    assert online.read_bytes() == before and not (online.parent/'imported.json').exists()
    r.close()
    r = open_replay(tmp_path/'r')
    r.wait_idle()
    try:
        for _ in range(4):
            assert r.sample(4).actions.shape == (4, 6)
            assert r.sample_human(2).actions.shape == (2, 6)
    finally:
        r.close()
    assert not r.worker.is_alive()


def test_periodic_direct_registration_matches_exported_records(tmp_path):
    from test_observation_storage import record_episode, equal
    config = HILConfig(wrist_camera='required')
    c = config.replay_contract()
    result, _ = record_episode(tmp_path/'data', 'source', config, gap=True)
    reference = {}
    for segment in result['segments']:
        path = tmp_path/'data/episodes'/segment
        for record in read_episode(path, json.loads((path/'ready.json').read_text())):
            reference[record['command_audit']['periodic_tick']] = record
    r = buffer(tmp_path/'r', c, slots=4)
    try:
        r.seal_seed()
        r.import_ready(tmp_path/'data');r.wait_idle()
        assert r.storage_stats()['catalog_online'] == len(reference) == 2
        for row in r.db.execute('SELECT * FROM records'):
            loaded = r._load(row)
            old = reference[row['step']]
            equal(loaded[0], old['observation']); equal(loaded[1], old['next_observation'])
            np.testing.assert_array_equal(loaded[2], old['executed_action'])
            assert loaded[3] == old['reward'] and loaded[4] == float(old['terminated'])
        assert r.stream_counts()['online'] == r.stream_counts()['intervention'] == 2
        assert len(list((tmp_path/'r').glob('*.npy'))) == 0
    finally:
        r.close()


def test_cached_prepare_clone_and_actual_learner_resume(tmp_path):
    import torch
    from omi_hil_rl.hil.prepare_bc_rl import prepare
    from omi_hil_rl.hil.async_training import initialize
    from omi_hil_rl.hil.exchange import atomic_json, atomic_torch
    from omi_hil_rl.hil.learner import run_learner
    from omi_hil_rl.hil.networks import SAC
    from omi_hil_rl.training.cached_replay import digest
    config = HILConfig()
    c = config.replay_contract()
    seed_path, manifest = episode(tmp_path/'seed_data', 'seed', c)
    online_path, _ = episode(tmp_path/'online_data', 'online', c, sources=('human', 'policy')*2)
    bc = tmp_path/'bc'; bc.mkdir()
    agent = SAC({'encoder':'synthetic-test'}, c)
    state = agent.checkpoint(); state['training_method']='behavior_cloning'
    atomic_torch(bc/'actor.pt', state)
    atomic_json(bc/'config.json', c['config'])
    atomic_json(bc/'dataset.json', dict(episodes=[dict(path=str(seed_path.parent),manifest=manifest,
        manifest_sha256=digest(seed_path),sample_sha256=[digest(seed_path.parent/'000000.npz')],split='training')]))
    prepared = tmp_path/'prepared'
    result = prepare(bc, prepared, replay_backend='cached', warmup=2,
                     cache_target_gib=.06, cache_limit_gib=.12, recorded_sources=[tmp_path/'online_data'])
    assert result['samples'] == 1
    run = tmp_path/'live'
    initialize(prepared, run)
    result = run_learner(run, config, batch_size=2, updates=4, publish_every=2, wait_seconds=20.)
    assert result['updates'] == 4
    assert result['streams']['online'] == 4 and result['streams']['demonstration'] == 3
    assert run_learner(run, config, batch_size=2, updates=2, wait_seconds=20.)['updates'] == 6
    with pytest.raises(TimeoutError):
        run_learner(run, config, batch_size=2, updates=1, wait_seconds=.5, max_updates_per_transition=1.)
    assert json.loads((run/'status.json').read_text())['waiting_for_update_budget']
    checkpoint = torch.load(run/'learner.pt', weights_only=True)
    assert any(not torch.equal(v, state['actor'][k]) for k,v in checkpoint['actor'].items())
    assert not list((run/'replay').rglob('*.npy'))
    assert not (online_path.parent/'imported.json').exists()


def test_changed_frame_file_stops_background_loading(tmp_path):
    c = contract()
    path,_ = episode(tmp_path/'data','seed',c)
    r = buffer(tmp_path/'r', c)
    register(r,path,True); r.close()
    sample = path.parent/'000000.npz'
    with sample.open('ab') as stream:
        stream.write(b'changed')
    r = CachedDualReplay.reopen(tmp_path/'r',prefetch=False)
    try:
        with pytest.raises(RuntimeError, match='file changed'):
            r.wait_idle()
        with pytest.raises(RuntimeError, match='background load failed'):
            r.sample_human(2)
    finally:
        r.close()


def test_initial_seed_cannot_be_recounted_as_online(tmp_path):
    c = contract()
    path,_ = episode(tmp_path/'data','seed',c)
    r = buffer(tmp_path/'r',c)
    try:
        register(r,path,True)
        with pytest.raises(ValueError,match='cannot also'):
            r.register_episode(path)
        assert r.storage_stats()['catalog_online']==0
    finally:
        r.close()


def test_sampling_continues_during_rollover_without_seed(tmp_path):
    import threading
    c = contract()
    first,_ = episode(tmp_path/'data','first',c,sources=('human','policy')*4)
    second,_ = episode(tmp_path/'data','second',c,sources=('human','policy')*5)
    r = buffer(tmp_path/'r',c,slots=3)
    errors=[]; stop=threading.Event()
    try:
        r.seal_seed();register(r,first)
        def sample():
            try:
                while not stop.is_set():
                    batch=r.sample(4)
                    assert batch.actions.shape==(4,6)
                    time.sleep(.001)
            except BaseException as exc:
                errors.append(exc)
        thread=threading.Thread(target=sample);thread.start()
        try:
            register(r,second)
            for _ in range(5):
                r.refresh();r.wait_idle()
        finally:
            stop.set();thread.join()
        assert not errors
        assert r.storage_stats()['catalog_online']==18 and len(r.cache)==3
    finally:
        r.close()


def test_pool_retirement_is_independent_of_shared_residency(tmp_path, monkeypatch):
    c=contract()
    seed,_=episode(tmp_path/'data','seed',c)
    source,_=episode(tmp_path/'data','online',c,sources=('human','human','policy','policy','policy'))
    r=buffer(tmp_path/'r',c,slots=5)
    try:
        register(r,seed,True);register(r,source)
        humans=[row[0] for row in r.db.execute('SELECT id FROM records WHERE seed=0 AND human=1 ORDER BY id')]
        policies={row[0] for row in r.db.execute('SELECT id FROM records WHERE human=0')}
        h,other=humans
        first_two=set(sorted(policies)[:2])
        plan={'demo':{h},'online':{h}|first_two}
        monkeypatch.setattr(r,'_select',lambda where,quota,previous:set(plan['demo' if 'human=1' in where else 'online']))
        r.refresh();r.wait_idle()
        assert h in r.demo and h in r.online
        shared=r.cache[h]

        # RL retires h. Demo still owns precisely the same arrays; h must not
        # silently be added back to RL simply because it remains resident.
        plan['online']=set(policies)
        r.refresh();r.wait_idle()
        assert h in r.demo and h not in r.online and r.cache[h] is shared
        draws=r.sample(40).actions.numpy()[:,0]
        assert np.count_nonzero(draws<.5)==20  # RL half now contains only policy records.

        # Demo also retires h: RAM can be reclaimed, but the catalog and original
        # sample file must survive so historical selection can load it again.
        plan['demo']={other}
        r.refresh();r.wait_idle()
        assert h not in r.demo and h not in r.online and h not in r.cache
        row=r.db.execute('SELECT * FROM records WHERE id=?',(h,)).fetchone()
        assert r._resolve(row['path']).is_file()

        # Reload h for RL only. Its human label does not force Demo membership.
        plan['online']={h}|first_two
        r.refresh();r.wait_idle()
        assert h in r.online and h not in r.demo and h in r.cache
        assert np.all(r.cache[h][2]==np.float32(.1))

        # Budget refusal also must not evict another stream's retained record.
        before=set(r.cache)
        with r.cv,pytest.raises(MemoryError):
            r._room(r.memory_limit_bytes)
        assert set(r.cache)==before
    finally:
        r.close()


def test_loading_rl_only_human_preserves_last_demo_until_replacement(tmp_path,monkeypatch):
    c=contract()
    path,_=episode(tmp_path/'data','online',c,sources=('human','human','human','policy','policy'))
    r=buffer(tmp_path/'r',c,slots=3)
    try:
        r.seal_seed();register(r,path)
        ids=[row[0] for row in r.db.execute('SELECT id FROM records ORDER BY step')]
        old_demo,new_rl,new_demo,p1,p2=ids
        plan={'demo':{old_demo},'online':{p1,p2}}
        monkeypatch.setattr(r,'_select',lambda where,quota,previous:set(plan['demo' if 'human=1' in where else 'online']))
        r.refresh();r.wait_idle()
        original=r._load
        observed=[]
        def check_mid_refresh(row):
            if row['id']==new_demo:
                assert new_rl in r.online and old_demo in r.demo
                observed.append(r.sample(2).actions.shape)
            return original(row)
        monkeypatch.setattr(r,'_load',check_mid_refresh)
        plan['demo']={new_demo};plan['online']={new_rl,p2}
        r.refresh();r.wait_idle()
        assert observed==[(2,6)]
        assert r.demo=={new_demo} and r.online=={new_rl,p2}
    finally:
        r.close()
