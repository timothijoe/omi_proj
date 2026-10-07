import json

import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.exchange import atomic_json
from omi_hil_rl.hil.offline_train import split_episodes


def source(tmp_path):
    config = HILConfig(review='auto')
    contract = config.replay_contract()
    atomic_json(tmp_path/'session.json', dict(config=contract['config'], contract=contract))
    for i in range(6):
        path = tmp_path/'episodes'/str(i)
        path.mkdir(parents=True)
        # Only split metadata is under test here, not sample decoding.
        (path/'000000.npz').touch()
        atomic_json(path/'ready.json', dict(contract=contract, keep=True, count=1,
                    episode=str(i), episode_success=i < 2, origin='online'))
    return tmp_path


def test_split_is_episode_disjoint_reproducible_and_stratified(tmp_path):
    src = source(tmp_path)
    _, _, train, val = split_episodes(src, 7)
    assert len(train) == 4 and len(val) == 2
    assert {m['episode'] for _, m in train}.isdisjoint({m['episode'] for _, m in val})
    assert {m['episode_success'] for _, m in train} == {True, False}
    assert {m['episode_success'] for _, m in val} == {True, False}
    assert split_episodes(src, 7)[2:] == (train, val)


def test_split_rejects_missing_samples(tmp_path):
    src = source(tmp_path)
    path = src/'episodes/0/ready.json'
    manifest = json.loads(path.read_text())
    manifest['count'] = 2
    atomic_json(path, manifest)
    with pytest.raises(ValueError, match='sample count'):
        split_episodes(src, 7)


def test_multiple_sessions_are_combined_without_episode_leakage(tmp_path):
    a, b = tmp_path/'a', tmp_path/'b'
    a.mkdir()
    b.mkdir()
    source(a)
    source(b)
    with pytest.raises(ValueError, match='duplicate episode'):
        split_episodes([a,b], 7)
    for path in b.glob('episodes/*/ready.json'):
        manifest = json.loads(path.read_text())
        manifest['episode'] = 'b-' + manifest['episode']
        atomic_json(path, manifest)
    _, _, train, val = split_episodes([a,b], 7)
    assert len(train) + len(val) == 12
    assert {m['episode'] for _,m in train}.isdisjoint({m['episode'] for _,m in val})
    with pytest.raises(ValueError, match='distinct'):
        split_episodes([a,a], 7)
    session = json.loads((b/'session.json').read_text())
    session['config']['episode_seconds'] = 20
    atomic_json(b/'session.json', session)
    with pytest.raises(ValueError, match='contracts differ'):
        split_episodes([a,b], 7)
