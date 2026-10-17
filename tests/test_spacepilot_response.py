"""Compare HIL against standalone motion, without opening devices or ROS."""
import argparse
from dataclasses import replace
import json
import math
from types import SimpleNamespace as NS

import numpy as np
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import FakeTransport
from omi_hil_rl.hil.periodic_control import observation_action, run_periodic
from omi_hil_rl.hil.periodic_replay import eligibility
from omi_hil_rl.real.operator_input import (
    InputOptions, SpacePilotHILMapping, collection_input_config, add_input_arguments,
)
from omi_hil_rl.real.spacepilot_control import SpacePilotMapping, MotionSchedule
from omi_hil_rl.real.sdk_action import output_action


def args(**changes):
    values=dict(input_device='spacepilot',config=None,resume=False,
                spacepilot_translation_scale=1.5,spacepilot_rotation_scale=.3,
                spacepilot_speed_profile='auto')
    values.update(changes)
    return NS(**values)


@pytest.mark.parametrize('translation,rotation', [(1.5,.3),(2.5,.3),(0,.3),(1.5,0)])
def test_fresh_collection_matches_standalone_all_axes_and_magnitudes(translation,rotation):
    old=HILConfig()
    cfg,opt=collection_input_config(old,args(spacepilot_translation_scale=translation,spacepilot_rotation_scale=rotation))
    assert opt.speed_profile=='standalone'
    mapping=SpacePilotHILMapping(cfg,opt)
    reference=SpacePilotMapping(translation_scale=translation,rotation_scale=rotation)
    samples=np.concatenate([np.eye(6)*350,-np.eye(6)*350,np.random.default_rng(42).uniform(-350,350,(100,6))])
    for raw in samples:
        actual=mapping.action(dict(enumerate(raw)))
        np.testing.assert_allclose(actual,reference.action(raw),rtol=1e-6,atol=1e-10)
        assert np.max(np.abs(cfg.normalized_action(actual)))<=1
    if translation==1.5:
        assert cfg.translation_step_m==pytest.approx(.0015)
        assert mapping.action({0:350})[0]*10*1000==pytest.approx(15)
    assert old.translation_step_m==HILConfig().translation_step_m


def test_old_sessions_and_gamepad_contracts_are_not_silently_rescaled():
    cfg=HILConfig()
    for supplied in (args(input_device='gamepad'),args(config='old.json'),args(resume=True),
                     args(spacepilot_speed_profile='session')):
        actual,opt=collection_input_config(cfg,supplied)
        assert actual==cfg
        if opt.kind=='spacepilot':
            assert opt.speed_profile=='session'
    with pytest.raises(ValueError,match='session/model action contract'):
        collection_input_config(cfg,args(config='old.json',spacepilot_speed_profile='standalone'))
    with pytest.raises(ValueError,match='session/model action contract'):
        SpacePilotHILMapping(cfg,InputOptions(speed_profile='standalone',translation_scale=1.5,rotation_scale=.3))


def test_wallclock_human_motion_starts_stops_and_restarts_between_observations(monkeypatch):
    import omi_hil_rl.hil.periodic_control as module
    now=[10.]
    monkeypatch.setattr(module,'time',NS(monotonic=lambda:now[0]))
    tr=NS(collect_human=True,latest=({},10_000_000_000),pad=NS(buttons={311:True},axes={}),
          mapping=NS(action=lambda axes:np.array(axes.get('action',[0.]*6),np.float32)),
          spacepilot_schedule=MotionSchedule())
    sent=[]
    used=None
    for t,action in [(10.,[0]*6),(10.01,[1,0,0,0,0,0]),(10.05,[0,1,0,0,0,0]),
                     (10.111,[0,1,0,0,0,0]),(10.14,[0]*6),(10.15,[1,0,0,0,0,0]),
                     (10.251,[1,0,0,0,0,0])]:
        now[0]=t;tr.pad.axes={'action':action}
        selection=observation_action(tr,used,{'human':True})
        if selection:
            adopted,source,gate,_,used,_=selection
            assert source==gate=='human'
            sent.append((t,adopted.copy(),tr.last_manual_timing))
            tr.spacepilot_schedule.sent(t,adopted)
    assert [r[0] for r in sent]==[10.,10.01,10.111,10.14,10.15,10.251]
    np.testing.assert_array_equal(sent[2][1],[0,1,0,0,0,0])
    assert sent[3][2]['motion_edge'] and not sent[3][1].any()
    # No catch-up burst after a delayed iteration.
    assert tr.spacepilot_schedule.due(11.,np.ones(6))
    tr.spacepilot_schedule.sent(11.,np.ones(6))
    assert not tr.spacepilot_schedule.due(11.001,np.ones(6))


def test_gamepad_still_waits_for_next_observation_and_policy_arbitration_unchanged(monkeypatch):
    tr=NS(collect_human=True,latest=({},100),pad=NS(buttons={311:True},axes={}),
          mapping=NS(action=lambda _:np.ones(6)),spacepilot_schedule=None)
    assert observation_action(tr,100,{'human':True}) is None
    tr.collect_human=False
    tr.spacepilot_schedule=MotionSchedule()
    tr.arbitration_mode='after-inference'
    tr.policy_pipeline=NS(take=lambda:None)
    assert observation_action(tr,None,{'human':True,'policy':True}) is None
    tr.policy_pipeline=NS(take=lambda:({},100,np.zeros(6),20.))
    assert observation_action(tr,None,{'human':True,'policy':True})[1]=='human'
    assert tr.last_manual_timing is None  # explicit deferred arbitration remains deferred


def test_idle_positioning_uses_same_fast_edges(monkeypatch):
    import omi_hil_rl.hil.ros_transport as module
    tr=module.RosTransport.__new__(module.RosTransport)
    now=[1.];sent=[]
    monkeypatch.setattr(module,'time',NS(monotonic=lambda:now[0]))
    tr.allow_manual_reset=True;tr.publisher=object();tr.home=None;tr.connected=True
    tr.pad=NS(buttons={311:True},axes={});tr.mapping=NS(action=lambda _:np.array([value[0],0,0,0,0,0]))
    tr.spacepilot_reset_schedule=MotionSchedule();tr.reset_requires_release=False
    tr._publish=lambda action:sent.append((now[0],action.copy()))
    value=[0.]
    tr._manual_reset_tick()
    now[0]=1.01;value[0]=.001;tr._manual_reset_tick()
    now[0]=1.02;value[0]=0;tr._manual_reset_tick()
    assert [stamp for stamp,_ in sent]==[1.,1.01,1.02]


def interval():
    tick=dict(command_id='test',observation_present=True,observation_reference_ns=1_000_000_000,
              command_send_ns=1_010_000_000,wire_action=[0.]*6,action_source='human',gate='human',
              manual_timing={'scheduling':'spacepilot_wallclock_10hz_edges_v1'})
    nxt=dict(observation_present=True,observation_reference_ns=1_100_000_000,command_send_ns=1_110_000_000)
    receipt=dict(command_id='test',accepted=True,status='velocity_zero_stopped',wire_action=[0.]*6,
                 arm='A',delta_frame='base',control_mode='velocity_hold',action_source='human',nominal_duration_s=.1)
    return tick,nxt,[receipt]


def test_fast_edge_audit_does_not_create_duplicate_or_short_training_steps():
    tick,nxt,receipts=interval()
    check=lambda:eligibility(tick,nxt,receipts,[],timing_policy='diagnostic_only_v1')
    assert check()=='valid'
    nxt['observation_reference_ns']=tick['observation_reference_ns']
    assert check()=='manual_reused_observation'
    nxt['observation_reference_ns']=1_100_000_000
    nxt['command_send_ns']=1_030_000_000
    assert check()=='manual_edge_or_gap_interval'
    nxt['command_send_ns']=1_110_000_000
    nxt['terminal_stop_ns']=1_040_000_000
    assert check()=='manual_edge_or_gap_interval'


def test_fast_collection_exports_true_normalized_commands_and_audits_every_edge(tmp_path,monkeypatch):
    import omi_hil_rl.hil.periodic_control as module
    now=[100.]
    monkeypatch.setattr(module,'time',NS(monotonic=lambda:now[0]))
    config,opt=collection_input_config(HILConfig(transport='ros',review='auto',episode_seconds=.7),args())
    obs=FakeTransport(config)._observation()
    pending=[];sent=[];stops=[]
    class Transport:
        def __init__(self):
            self.collect_human=True;self.connected=True;self.latest=None
            self.pad=NS(buttons={},axes={})
            self.mapping=SpacePilotHILMapping(config,opt)
            self.spacepilot_schedule=MotionSchedule()
            self.events=set();self.event_times={};self.latest_eef_time=0
            self.node=NS(get_clock=lambda:NS(now=lambda:NS(nanoseconds=int(now[0]*1e9))))
        def wait_start(self):return now[0]
        def start_episode(self):self.spacepilot_schedule.reset()
        def stop(self):stops.append(now[0])
        def idle_tick(self):pass
        def _pump(self):
            now[0]=round(now[0]+.01,6)
            elapsed=round(now[0]-100,6)
            self.latest=(obs,int(math.floor((elapsed+1e-7)*10))*100_000_000+100_000_000_000)
            self.latest_eef_time=int(now[0]*1e9)
            self.pad.buttons={311:True}
            self.pad.axes={0:350 if .02<=elapsed<.14 or .16<=elapsed<.49 else 0}
            for deadline,receipt in list(pending):
                if now[0]>=deadline:
                    pending.remove((deadline,receipt))
                    if getattr(self,'receipt_hook',None):self.receipt_hook(receipt)
        def _publish(self,action,command_id):
            wire=output_action(action,config.sdk_convention)
            self.last_command_trace={'command_send_ns':int(now[0]*1e9),'action_m_rad':action.tolist()}
            sent.append((now[0],wire))
            receipt=dict(command_id=command_id,accepted=True,finished=True,
                         status='queue_accepted' if any(wire) else 'velocity_zero_stopped',
                         control_mode='velocity_hold',arm='A',delta_frame='base',nominal_duration_s=.1,
                         action_source='human',wire_action=wire,timestamp_ns=int((now[0]+.001)*1e9))
            pending.append((round(now[0]+.01,6),receipt))
            return wire
    tr=Transport();finished=[]
    actor=NS(transport=tr,config=config,run=tmp_path,version=0,load=lambda:None,
             close_pipeline=lambda:None,state=lambda *a,**kw:None,finished=finished.append)
    run_periodic(actor,1,training=True)
    assert any(t==100.02 and wire[0]==pytest.approx(1.5) for t,wire in sent)
    assert any(t==100.14 and not any(wire) for t,wire in sent)
    assert any(t==100.16 and wire[0]==pytest.approx(1.5) for t,wire in sent)
    assert any(t==100.49 and not any(wire) for t,wire in sent)
    audit=json.loads(next(tmp_path.glob('periodic_episodes/*/audit.json')).read_text())
    assert audit['ticks']==len(sent) and audit['training_ready']
    assert audit['excluded'].get('manual_reused_observation',0)>0
    from omi_hil_rl.hil.exchange import read_episode
    records=[]
    for path in tmp_path.glob('episodes/*/ready.json'):
        records.extend(read_episode(path.parent,json.loads(path.read_text())))
    assert records
    for record in records:
        meta=record['command_audit']
        assert .08<=meta['actual_command_interval_s']<=.15
        assert record['next_observation_time_ns']>record['observation_time_ns']
        wire=output_action(config.physical_action(record['executed_action']),config.sdk_convention)
        np.testing.assert_allclose(wire,meta['receipts'][0]['wire_action'],atol=1e-7)
