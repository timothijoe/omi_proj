from copy import deepcopy
from types import SimpleNamespace as NS

import numpy as np
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.exploration import GaussianExploration
from omi_hil_rl.hil.periodic_control import observation_action


@pytest.mark.parametrize('std,clip', [(-.1,.15), (float('nan'),.15), (float('inf'),.15),
                                     (1.1,.15), (.05,0), (.05,float('nan')), (.05,1.1)])
def test_invalid_exploration_parameters(std, clip):
    with pytest.raises(ValueError):
        GaussianExploration(std, clip)


def test_noise_bounds_final_clipping_and_disabled_identity():
    mean = np.array([.99, -.99, 0, 0, .5, -.5], np.float32)
    exploration = GaussianExploration(.05, .15)
    exploration.rng = NS(normal=lambda *args: np.array([10, -10, 10, -10, 0, 0]))
    output, audit = exploration.apply(mean)
    np.testing.assert_allclose(output, [1, -1, .15, -.15, .5, -.5])
    np.testing.assert_allclose(np.array(audit['mean_action'])+audit['applied_delta'], output, atol=1e-7)
    assert max(abs(np.array(audit['clipped_noise']))) <= .150001
    assert mean[0] == np.float32(.99)  # caller's candidate stays intact
    disabled = GaussianExploration(0, seed=7)
    state = deepcopy(disabled.rng.bit_generator.state)
    actual, metadata = disabled.apply(mean)
    np.testing.assert_array_equal(actual, mean)
    assert metadata is None and disabled.rng.bit_generator.state == state
    for invalid in ([float('nan')]*6, [2]*6, [0]*5):
        with pytest.raises(ValueError):
            disabled.apply(invalid)


@pytest.mark.parametrize('mode', ['after-inference', 'immediate'])
def test_only_selected_policy_draws_noise_human_and_handshake_unchanged(mode):
    config = HILConfig()
    mean = np.full(6, .2, np.float32)
    exploration = GaussianExploration(.05, .15, seed=7)
    human = np.full(6, .0001, np.float32)
    tr = NS(latest=({},100), config=config, pad=NS(buttons={},axes={}),
            mapping=NS(action=lambda axes:human), arbitration_mode=mode,
            policy_exploration=exploration,
            policy_pipeline=NS(take=lambda: ({},100,mean,10.)))
    state = deepcopy(exploration.rng.bit_generator.state)
    action, _, gate, *_ = observation_action(tr,None,{'human':False,'policy':False})
    assert gate=='receiver_handshake' and not action.any() and tr.last_exploration is None
    assert exploration.rng.bit_generator.state==state
    action, source, gate, *_ = observation_action(tr,None,{'human':True,'policy':True})
    assert source==gate=='policy' and tr.last_exploration is not None
    assert not np.array_equal(config.normalized_action(action),mean)
    np.testing.assert_allclose(config.normalized_action(action),
        np.array(tr.last_exploration['mean_action'])+tr.last_exploration['applied_delta'],atol=1e-7)
    state=deepcopy(exploration.rng.bit_generator.state)
    tr.pad.buttons[311]=True
    action, source, gate, *_=observation_action(tr,None,{'human':True,'policy':True})
    np.testing.assert_array_equal(action,human)
    assert source==gate=='human' and tr.last_exploration is None
    assert exploration.rng.bit_generator.state==state
    tr.pad.buttons[311]=False
    tr.policy_pipeline.take=lambda:None
    assert observation_action(tr,None,{'policy':True}) is None
    assert exploration.rng.bit_generator.state==state


def test_cli_rejects_invalid_noise_before_robot_connection(tmp_path, monkeypatch):
    import sys
    import omi_hil_rl.hil.async_training as module
    monkeypatch.setattr(module,'make_transport',lambda *a:pytest.fail('must not connect'))
    for options in (['--exploration-noise-std','nan'], ['--exploration-noise-std','.05'],
                    ['--execute','--exploration-noise-std','.05']):
        monkeypatch.setattr(sys,'argv',['async_training','--run',str(tmp_path),*options])
        with pytest.raises(SystemExit):
            module.main()


def test_actor_persists_exploration_configuration(tmp_path):
    import json
    from omi_hil_rl.hil.async_training import AsyncActor
    from omi_hil_rl.hil.environment import FakeTransport
    actor=AsyncActor(tmp_path,HILConfig(),FakeTransport(),device='cpu',policy=True,
                     exploration_noise_std=.05,exploration_noise_clip=.15)
    actor.state('WAIT_START')
    assert actor.transport.policy_exploration is actor.exploration
    assert json.loads((tmp_path/'async_state.json').read_text())['exploration']==actor.exploration.config()


def test_noisy_executed_label_and_audit_survive_both_replay_paths(tmp_path):
    import json
    from omi_hil_rl.hil.environment import FakeTransport
    from omi_hil_rl.hil.exchange import read_episode
    from omi_hil_rl.hil.periodic_control import PeriodicAudit
    from omi_hil_rl.real.sdk_action import output_action
    from omi_hil_rl.training.replay_sources import periodic_records
    from omi_hil_rl.training.transition_replay import TransitionReplay
    config=HILConfig(wrist_camera='required'); contract=config.replay_contract()
    obs=FakeTransport(config)._observation()
    obs['history_mask'][:]=1; obs['camera_mask'][:]=1
    exploration=GaussianExploration(.05,.15,seed=7)
    writer=PeriodicAudit(tmp_path,'noisy',contract,7,training=True,timing_policy='diagnostic_only_v1')
    expected=[]
    for i in range(2):
        stamp=1_000_000_000+i*100_000_000
        action,trace=exploration.apply(np.full(6,.2,np.float32)); expected.append((action,trace))
        wire=output_action(config.physical_action(action),config.sdk_convention)
        writer.submit('tick',(dict(command_id=str(i),action_source='policy',gate='policy',
            command_trace={},exploration=trace,observation_present=True,
            observation_reference_ns=stamp,command_send_ns=stamp+1_000_000,eef_receive_ns=stamp-1,
            normalized_action=action.tolist(),wire_action=wire),obs))
        writer.submit('receipt',dict(command_id=str(i),accepted=True,finished=False,status='queue_accepted',
            timestamp_ns=stamp+2_000_000,wire_action=wire,arm='A',delta_frame='base',
            action_source='policy',control_mode='velocity_hold',nominal_duration_s=.1))
    result=writer.finish((dict(observation_present=True,observation_reference_ns=1_200_000_000,
        eef_receive_ns=1_199_000_000,command_send_ns=1_201_000_000),obs),
        dict(episode='noisy',policy_version=7,success=True,reason='success'))
    assert result['training_ready'] and result['transitions']==2
    exported=[]
    for segment in result['segments']:
        path=tmp_path/'episodes'/segment
        exported.extend(read_episode(path,json.loads((path/'ready.json').read_text())))
    replay=TransitionReplay(tmp_path/'replay',contract,4,prefetch=False)
    try:
        direct=[r for _,_,r in periodic_records(tmp_path/'periodic_episodes/noisy',contract,replay,{})]
        assert len(direct)==len(exported)==2
        for records in (exported,direct):
            for record,(action,trace) in zip(records,expected):
                np.testing.assert_array_equal(record['executed_action'],action)
                assert record['command_audit']['exploration']==trace
                assert record['action_source']=='policy'
            assert records[-1]['reward']==1 and records[-1]['terminated']
    finally:
        replay.close()
