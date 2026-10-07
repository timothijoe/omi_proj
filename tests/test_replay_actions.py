import json
from types import SimpleNamespace

import numpy as np
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.replay_actions import load_actions, play
from omi_hil_rl.real.gamepad_control import wire_action


def fixture_episode(path):
    config = HILConfig(transport='ros', review='auto')
    manifest = dict(keep=True, episode_success=True, episode='test', count=1,
                    contract=config.replay_contract())
    (path/'ready.json').write_text(json.dumps(manifest))
    action = np.array([.7, 0, -.7, 0, .2, 0], np.float32)
    physical = config.physical_action(action)
    wire = wire_action(physical, config.sdk_convention)
    meta = dict(step=0, episode='test', terminated=True, action_source='human',
        command_audit=dict(command_send_ns=100, wire_action=wire,
            command_trace=dict(action_m_rad=physical.tolist()),
            receipt=dict(accepted=True, finished=True, arm='A', delta_frame='base',
                         control_mode='velocity_hold', nominal_duration_s=.1, wire_action=wire)))
    state = np.zeros((10, 14), np.float32)
    state[:, -1] = 1
    np.savez(path/'000000.npz', metadata=json.dumps(meta), executed_action=action,
             observation__state=state)
    return config, manifest


def test_load_preserves_policy_space_and_checks_wire(tmp_path):
    config, manifest = fixture_episode(tmp_path)
    _, _, rows, pose = load_actions(tmp_path)
    assert rows[0]['normalized'][0] == pytest.approx(.7)
    assert rows[0]['wire'] == wire_action(config.physical_action(rows[0]['normalized']), config.sdk_convention)
    manifest['episode_success'] = False
    (tmp_path/'ready.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='success-labelled'):
        load_actions(tmp_path)


@pytest.mark.parametrize('rb', [False, True])
def test_play_policy_route_and_rb_cancels(tmp_path, monkeypatch, rb):
    import omi_hil_rl.hil.replay_actions as module
    fixture_episode(tmp_path)
    _, config, rows, pose = load_actions(tmp_path)
    rows = [dict(rows[0], step=i, send_ns=i*100_000_000) for i in range(3)]
    now = [0.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(module, 'check_pose', lambda *args: None)
    sent = []
    class Transport:
        def __init__(self):
            self.receipts = {}
            self.events = set()
            self.connected = True
            self.pad = SimpleNamespace(buttons={})
        def wait_start(self): pass
        def _pump(self):
            now[0] += .005
            if rb and len(sent) >= 2:
                self.pad.buttons[311] = True
        def _publish(self, action, cid):
            assert self.last_owner == 'policy'
            wire = wire_action(action, config.sdk_convention)
            sent.append(wire)
            self.receipts[cid] = dict(accepted=True, action_source='policy',
                control_mode='velocity_hold', arm='A', delta_frame='base',
                nominal_duration_s=.1, wire_action=wire)
            return wire
    result = play(Transport(), config, rows, pose, lambda value: None)
    assert sent[0] == [0.]*6
    assert sent[1] == rows[0]['wire']
    assert len(sent) == (2 if rb else 4)
    assert result == ('RB_cancelled_replay' if rb else 'sequence_finished_not_task_success')
