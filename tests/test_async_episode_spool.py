import json
import threading
from pathlib import Path

import numpy as np
import pytest

from omi_hil_rl.hil.async_spool import AsyncEpisodeSpool, RecordingError
from omi_hil_rl.hil.exchange import EpisodeSpool
from omi_hil_rl.hil.config import HILConfig


def args(step=0, terminal=True):
    return ({'state': np.ones(4)}, {'state': np.ones(4)*2}, float(terminal), terminal, False,
            dict(episode='test', step=step, observation_time_ns=step+1,
                 next_observation_time_ns=step+2, action_source='human',
                 command_status='test', executed_action=np.zeros(6), command_audit={'id': 1}))


def test_writer_is_separate_and_snapshot_owned(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = EpisodeSpool.append
    threads = []
    def slow(self, *values):
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(3)
        original(self, *values)
    monkeypatch.setattr(EpisodeSpool, 'append', slow)
    spool = AsyncEpisodeSpool(tmp_path, 'test', HILConfig().replay_contract())
    values = args()
    try:
        spool.append(*values)
        assert entered.wait(3)  # append returned while disk writer is still blocked
        values[0]['state'][:] = 99
        values[-1]['command_audit']['id'] = 99
        assert not list(tmp_path.glob('episodes/*/ready.json'))
    finally:
        release.set()
    result = spool.finish(True)
    assert result['keep'] and threads != [threading.get_ident()]
    with np.load(tmp_path/'episodes/test/000000.npz') as z:
        assert np.all(z['observation__state'] == 1)
        assert json.loads(str(z['metadata']))['command_audit']['id'] == 1
    assert not spool.thread.is_alive()


def test_queue_full_excludes_episode_and_drains_submitted_prefix(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = EpisodeSpool.append
    def slow(self, *values):
        entered.set()
        assert release.wait(3)
        original(self, *values)
    monkeypatch.setattr(EpisodeSpool, 'append', slow)
    spool = AsyncEpisodeSpool(tmp_path, 'test', HILConfig().replay_contract(), capacity=1)
    try:
        spool.append(*args(0, False))
        assert entered.wait(3)
        spool.append(*args(1, False))
        with pytest.raises(RecordingError, match='queue full'):
            spool.append(*args(2))
    finally:
        release.set()
    result = spool.finish(True)
    assert not result['keep'] and result['count'] == 2
    assert not list(tmp_path.glob('episodes/*/ready.json'))


def test_disk_error_cannot_publish_ready(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(EpisodeSpool, 'append', fail)
    spool = AsyncEpisodeSpool(tmp_path, 'test', HILConfig().replay_contract())
    spool.append(*args())
    result = spool.finish(True)
    assert not result['keep'] and 'disk full' in result['reason']
    assert not list(tmp_path.glob('episodes/*/ready.json'))


def test_finish_wait_services_idle_and_prefix_outcome(tmp_path):
    spool = AsyncEpisodeSpool(tmp_path, 'test', HILConfig().replay_contract())
    spool.append(*args(0, False))
    spool.finish_valid_prefix(success=False)
    result = spool.finish(True)
    assert result['keep'] and not result['episode_success']
    with np.load(tmp_path/'episodes/test/000000.npz') as z:
        assert json.loads(str(z['metadata']))['truncated']


def test_finish_pumps_manual_control_while_waiting(tmp_path, monkeypatch):
    release = threading.Event()
    original = EpisodeSpool.append
    def slow(self, *values):
        assert release.wait(3)
        original(self, *values)
    monkeypatch.setattr(EpisodeSpool, 'append', slow)
    spool = AsyncEpisodeSpool(tmp_path, 'test', HILConfig().replay_contract())
    spool.append(*args())
    ticks = []
    def tick():
        ticks.append(True)
        release.set()
    assert spool.finish(True, tick=tick)['keep']
    assert ticks
