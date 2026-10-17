"""HIL input switching: no ROS/device/robot/learner is started by these tests."""
import argparse
from dataclasses import replace
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS

import numpy as np
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import ButtonEvents
from omi_hil_rl.hil.periodic_control import observation_action
from omi_hil_rl.real.gamepad_control import Mapping, wire_action
from omi_hil_rl.real.operator_input import (
    PROFILE_SCHEMA, PROFILE_FRAME, InputOptions, SpacePilotInput, SpacePilotHILMapping,
    add_input_arguments, options_from_args, load_button_profile, create_operator_input,
    check_operator_input, required_buttons, button_labels,
    FOLLOW_TOGGLE, FOLLOW_SAVE, DirectFollowButtons, oct17_buttons, follow_buttons_for_input,
)
from omi_hil_rl.real.tag_follow import FollowButtons, FollowButtonFilter
from omi_hil_rl.real.gamepad_gripper import GripperButtons

ROOT = Path(__file__).resolve().parents[1]
# Synthetic confirmed bindings; only 311->19 is based on this user's device.
BUTTONS = {311:19,315:12,308:13,307:14,314:15,304:16,305:17,310:18}


def profile(tmp_path, buttons=None):
    p=tmp_path/'buttons.json'
    p.write_text(json.dumps(dict(schema=PROFILE_SCHEMA,axis_frame=PROFILE_FRAME,
                                buttons={str(k):v for k,v in (buttons or BUTTONS).items()})))
    return p


class Driver:
    def __init__(self, on_button, on_reset):
        self.on_button, self.on_reset = on_button, on_reset
        self.connected, self.name, self.message = True, 'SpacePilot PRO', 'SpacePilot PRO'
        self.raw, self.last_motion = [0]*6, 1.
        self.events = []
        self.reset_next = False
        self.closed = 0

    def poll(self, now):
        if self.reset_next:
            self.on_reset()
            self.reset_next = False
        for event in self.events:
            self.on_button(*event)
        self.events = []

    def close(self):
        self.connected = False
        self.closed += 1
        self.on_reset()


def input_device():
    clock=NS(now=1.)
    pad=SpacePilotInput(BUTTONS,driver_factory=Driver,clock=lambda:clock.now)
    assert pad.poll()
    return pad,clock


def test_default_input_is_exactly_the_existing_gamepad(monkeypatch):
    from omi_hil_rl.real import linux_gamepad
    sentinel=NS()
    paths=[]
    monkeypatch.setattr(linux_gamepad,'LinuxGamepad',lambda path:paths.append(path) or sentinel)
    parser=argparse.ArgumentParser();add_input_arguments(parser)
    options=options_from_args(parser.parse_args([]))
    config=HILConfig(transport='ros')
    pad,mapping,info=create_operator_input(config,'/old/joystick',options)
    assert pad is sentinel and paths==['/old/joystick']
    assert info==dict(kind='gamepad',device='/old/joystick')
    assert type(mapping) is Mapping
    old=Mapping(hz=config.hz,translation_m_s=config.translation_step_m*config.hz,
                rotation_rad_s=config.rotation_step_rad*config.hz)
    for axes in ({4:-.7,3:.2},{17:-1},{16:1,0:.8},{}, {4:-1,3:-1,17:1}):
        np.testing.assert_array_equal(mapping.action(axes),old.action(axes))


def test_profile_roundtrip_and_factory_never_opens_gamepad(tmp_path,monkeypatch):
    from omi_hil_rl.real import linux_gamepad
    from omi_hil_rl.hardware import spacepilot_pose
    monkeypatch.setattr(linux_gamepad,'LinuxGamepad',lambda *_:pytest.fail('opened gamepad'))
    monkeypatch.setattr(spacepilot_pose,'SpaceNav',Driver)
    p=profile(tmp_path)
    buttons,info=load_button_profile(p)
    assert buttons==BUTTONS and len(info['profile_sha256'])==64
    pad,mapping,info=create_operator_input(HILConfig(),options=InputOptions(kind='spacepilot',profile=p))
    assert isinstance(pad,SpacePilotInput) and isinstance(mapping,SpacePilotHILMapping)
    assert info['kind']=='spacepilot' and set(pad.button_map)==set(BUTTONS)
    pad.close()


@pytest.mark.parametrize('buttons', [{'311':True},{'311':19,'315':19},{'0311':19},{'315':12},{'311':-1}])
def test_invalid_profiles_rejected(tmp_path,buttons):
    p=tmp_path/'bad.json';p.write_text(json.dumps(dict(schema=PROFILE_SCHEMA,axis_frame=PROFILE_FRAME,buttons=buttons)))
    with pytest.raises(ValueError):load_button_profile(p)


def test_missing_and_changed_profile_fail_before_runtime(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match='configure_spacepilot_hil'):load_button_profile(tmp_path/'missing')
    p=profile(tmp_path);_,info=load_button_profile(p)
    options=InputOptions(kind='spacepilot',profile=p,expected_profile_sha256=info['profile_sha256'])
    p.write_text(p.read_text()+'\n')
    with pytest.raises(ValueError,match='changed after input preflight'):
        create_operator_input(HILConfig(),options=options)


def test_required_buttons_cover_episode_home_gripper_follow_review():
    c=HILConfig(review='auto')
    assert required_buttons(c)=={311,315,308,307}
    assert required_buttons(c,314,gripper=True,tag_follow=True)==set(BUTTONS)
    custom=replace(c,review='manual',keep_button=400,discard_button=401)
    assert {400,401}<=required_buttons(custom)
    assert {304,305,400,401}<=set(button_labels(custom))


def test_short_pulses_reach_episode_edges_once():
    pad,clock=input_device();events=ButtonEvents(HILConfig())
    events.poll(True,pad.buttons,pad.button_events)
    for logical,role in ((315,'start'),(308,'success'),(307,'manual_stop'),(304,'keep'),(305,'discard')):
        pad.driver.events=[(BUTTONS[logical],True),(BUTTONS[logical],False)]
        assert pad.poll()
        assert events.poll(True,pad.buttons,pad.button_events)=={role}
        assert pad.poll()
        assert events.poll(True,pad.buttons,pad.button_events)==set()


def test_held_buttons_on_startup_and_reconnect_require_release():
    clock=NS(now=1.)
    pad=SpacePilotInput(BUTTONS,driver_factory=Driver,clock=lambda:clock.now)
    pad.driver.events=[(19,True),(12,True)]
    assert pad.poll() and not any(pad.buttons.values())
    pad.driver.events=[(19,False),(12,False),(19,True)]
    assert pad.poll() and pad.buttons[311]
    pad.driver.reset_next=True
    assert not pad.poll() and not pad.buttons and not pad.axes
    pad.driver.events=[(19,True)]
    assert pad.poll() and not pad.buttons[311]
    pad.driver.events=[(19,False),(19,True)]
    assert pad.poll() and pad.buttons[311]


def test_stale_motion_zeroes_but_does_not_turn_human_into_policy():
    pad,clock=input_device()
    pad.driver.events=[(19,True)];pad.driver.raw=[0,0,200,0,0,150]
    assert pad.poll() and pad.buttons[311] and pad.axes[2]==200
    clock.now=1.16
    assert pad.poll() and pad.buttons[311]
    assert all(pad.axes[i]==0 for i in range(6))
    pad.driver.connected=False
    assert not pad.poll() and not pad.buttons


def test_stalled_poll_flushes_old_inputs_and_disables():
    pad,clock=input_device();pad.driver.events=[(19,True)];pad.poll()
    clock.now+=.3
    assert not pad.poll() and pad.driver.closed==1
    assert not pad.buttons and not pad.axes


def test_all_six_axes_remain_analog_and_fit_unchanged_contract():
    config=HILConfig(transport='ros')
    contract=config.replay_contract()
    mapping=SpacePilotHILMapping(config,InputOptions(kind='spacepilot'))
    for axis in range(6):
        physical=mapping.action({axis:184})  # (184-18)/(350-18)=0.5, including Z/Rz
        expected=np.zeros(6);expected[axis]=.5
        np.testing.assert_allclose(config.normalized_action(physical),expected,atol=1e-7)
    assert config.replay_contract()==contract


def test_independent_scales_saturate_within_replay_limits_preserving_direction():
    config=HILConfig()
    m=SpacePilotHILMapping(config,InputOptions(kind='spacepilot',translation_scale=3,rotation_scale=.2))
    a=m.action({0:350,1:184,3:350})
    normalized=config.normalized_action(a)
    assert normalized[0]==pytest.approx(1)
    assert normalized[1]==pytest.approx(.5)
    assert normalized[3]==pytest.approx(.2)
    m=SpacePilotHILMapping(config,InputOptions(kind='spacepilot',rotation_scale=0,dominant=True))
    assert m.action({0:150,3:350})[0]>0
    assert not m.action({0:150,3:350})[3:].any()


def test_home_gripper_and_lb_chords_use_existing_semantics():
    pad,clock=input_device();follow=FollowButtons();flt=FollowButtonFilter();gripper=GripperButtons()
    follow.select(True,pad.buttons,());gripper.select(True,{},())
    pad.driver.events=[(18,True),(16,True),(16,False),(18,False)]
    pad.poll()
    gb,ge=flt.gripper_input(pad.buttons,pad.button_events)
    assert gripper.select(True,gb,ge) is None
    assert follow.select(True,pad.buttons,pad.button_events)=='toggle'
    pad.driver.events=[(18,True),(17,True),(17,False),(18,False)];pad.poll()
    gb,ge=flt.gripper_input(pad.buttons,pad.button_events)
    assert gripper.select(True,gb,ge) is None
    assert follow.select(True,pad.buttons,pad.button_events)=='save'
    pad.driver.events=[(16,True),(16,False)];pad.poll()
    gb,ge=flt.gripper_input(pad.buttons,pad.button_events)
    assert gripper.select(True,gb,ge)=='close'
    pad.driver.events=[(17,True),(17,False)];pad.poll()
    assert gripper.select(True,pad.buttons,pad.button_events)=='open'
    pad.driver.events=[(15,True)];pad.poll()
    assert pad.buttons[314] and not pad.buttons.get(311,False)


def test_after_inference_arbitration_uses_spacepilot_only_for_human():
    config=HILConfig(transport='ros');pad,clock=input_device()
    pad.driver.events=[(19,True)];pad.driver.raw=[184,0,0,0,0,0];pad.poll()
    mapping=SpacePilotHILMapping(config,InputOptions(kind='spacepilot',translation_scale=.4))
    obs={'test':'actual inference input'}
    tr=NS(config=config,connected=True,pad=pad,mapping=mapping,latest=(obs,123),
          arbitration_mode='after-inference',policy_pipeline=NS(take=lambda:(obs,123,np.full(6,.3),.02)))
    result=observation_action(tr,None,{'human':True,'policy':True})
    assert result[1]=='human' and result[3][0] is obs
    np.testing.assert_allclose(config.normalized_action(result[0]),[.2,0,0,0,0,0])
    assert tr.last_exploration is None
    pad.driver.events=[(19,False)];pad.poll()
    result=observation_action(tr,None,{'human':True,'policy':True})
    assert result[1]=='policy'
    np.testing.assert_allclose(config.normalized_action(result[0]),[.3]*6)


def test_human_collection_records_analog_action_with_human_source():
    c=HILConfig(transport='ros');pad,clock=input_device()
    pad.driver.events=[(19,True)];pad.driver.raw=[0,0,184,0,0,0];pad.poll()
    tr=NS(config=c,connected=True,pad=pad,mapping=SpacePilotHILMapping(c,InputOptions(kind='spacepilot')),
          latest=({},1),collect_human=True)
    result=observation_action(tr,None,{'human':True,'policy':True},policy=False)
    assert result[1]=='human'
    np.testing.assert_allclose(c.normalized_action(result[0]),[0,0,.5,0,0,0])
    pad.driver.events=[(19,False)];pad.poll();tr.latest=({},2)
    result=observation_action(tr,1,{'human':True,'policy':True},policy=False)
    assert result[1]=='human' and not result[0].any()


def test_tagged_wire_and_trace_keep_human_label_and_profile(monkeypatch):
    from omi_hil_rl.hil.ros_transport import RosTransport
    class Message:
        def __init__(self,data):self.data=data;self.layout=NS(dim=[])
    monkeypatch.setitem(sys.modules,'std_msgs.msg',NS(Float64MultiArray=Message,MultiArrayDimension=lambda **kw:NS(**kw)))
    tr=RosTransport.__new__(RosTransport);sent=[]
    tr.config=HILConfig(transport='ros');tr.convention='sdk-x-forward-z-left';tr.topic='/manual'
    tr.competing_topics=[];tr.last_owner='human';tr.publisher=NS(publish=sent.append)
    tr.node=NS(count_publishers=lambda _:1,get_clock=lambda:NS(now=lambda:NS(nanoseconds=42)))
    tr.operator_input_info=dict(kind='spacepilot',profile_sha256='test-profile')
    a=tr.config.physical_action([0,0,.5,0,0,.25])
    wire=tr._publish(a,'hil:test-human')
    assert wire==wire_action(a,'sdk-x-forward-z-left') and sent[0].layout.dim[0].label=='hil:test-human'
    assert tr.last_command_trace['action_source']=='human'
    assert tr.last_command_trace['operator_input']['profile_sha256']=='test-profile'
    np.testing.assert_allclose(tr.last_command_trace['normalized_action'],[0,0,.5,0,0,.25])


@pytest.mark.parametrize('module',['collect_episodes','async_training','bc_rollout','alternating','actor'])
def test_public_entry_help_advertises_opt_in_without_hardware(module):
    p=subprocess.run([sys.executable,'-m','omi_hil_rl.hil.'+module,'--help'],capture_output=True,text=True,timeout=20)
    assert p.returncode==0,p.stderr
    assert '--input-device' in p.stdout and '--spacepilot-map' in p.stdout
    assert '--spacepilot-rotation-scale' in p.stdout


def test_explicit_assignment_creates_complete_profile_without_devices(tmp_path):
    dest=tmp_path/'profile.json'
    cmd=[sys.executable,str(ROOT/'scripts/configure_spacepilot_hil.py'),'--output',str(dest)]
    for logical,raw in BUTTONS.items():cmd += ['--assign',f'{logical}={raw}']
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert load_button_profile(dest)[0]==BUTTONS
    before=dest.read_bytes()
    assert subprocess.run(cmd,capture_output=True,timeout=10).returncode!=0
    assert dest.read_bytes()==before


def test_ros_transport_owns_publishers_and_spacepilot_never_constructs_gamepad(tmp_path,monkeypatch):
    from omi_hil_rl.hil import ros_transport as rt
    from omi_hil_rl.hardware import spacepilot_pose
    from types import ModuleType
    ros=ModuleType('rclpy');ros.__path__=[]
    qos=ModuleType('rclpy.qos');qos.qos_profile_sensor_data='sensor'
    qos.QoSProfile=lambda **kw:kw;qos.ReliabilityPolicy=NS(RELIABLE='reliable')
    nodes,publishers=[],[]
    node=NS(create_subscription=lambda *a:None,destroy_node=lambda:None)
    def publisher(kind,topic,quality):
        publishers.append(topic)
        return NS(publish=lambda msg:None)
    node.create_publisher=publisher
    ros.ok=lambda:True
    ros.create_node=lambda name,**kw:nodes.append(name) or node
    monkeypatch.setitem(sys.modules,'rclpy',ros)
    monkeypatch.setitem(sys.modules,'rclpy.qos',qos)
    monkeypatch.setitem(sys.modules,'sensor_msgs.msg',NS(Image=object))
    monkeypatch.setitem(sys.modules,'geometry_msgs.msg',NS(PoseStamped=object))
    monkeypatch.setitem(sys.modules,'std_msgs.msg',NS(Float64MultiArray=object,String=object))
    monkeypatch.setattr(rt,'StackObservations',lambda *a,**kw:NS(topics={}))
    monkeypatch.setattr(rt,'LinuxGamepad',lambda *a:pytest.fail('SpacePilot tried to create gamepad'))
    monkeypatch.setattr(spacepilot_pose,'SpaceNav',Driver)
    tr=rt.RosTransport(HILConfig(transport='ros',review='auto'),{},execute=True,
                       input_options=InputOptions(kind='spacepilot',profile=profile(tmp_path)))
    try:
        assert nodes==['omi_hil_actor']
        assert publishers==['/omi/action/decision','/omi/action/command_trace']
        assert isinstance(tr.pad,SpacePilotInput)
        assert tr.operator_input_info['kind']=='spacepilot'
    finally:tr.close()


def test_wizard_captures_press_release_and_rejects_chords(monkeypatch):
    spec=importlib.util.spec_from_file_location('spacepilot_setup',ROOT/'scripts/configure_spacepilot_hil.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    # Startup, pre-prompt drain, ambiguous chord, valid role1, next drain, role2.
    batches=[[],[],[(17,True),(19,True),(17,False),(19,False)],
             [(19,True),(19,False)],[],[(12,True),(12,False)]]
    class WizardDriver:
        def __init__(self,on_button,on_reset):
            self.connected=False;self.name='';self.message='test';self.button=on_button
        def poll(self,now):
            self.connected=True;self.name='SpacePilot'
            assert batches,'wizard failed to consume expected events'
            for event in batches.pop(0):self.button(*event)
        def close(self):pass
    monkeypatch.setattr(module,'SpaceNav',WizardDriver)
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    mapping,name=module.capture({311:'takeover',315:'start'})
    assert mapping=={311:19,315:12} and not batches


def test_legacy_bc_capture_help_supports_spacepilot():
    p=subprocess.run([sys.executable,'-m','omi_hil_rl.hil.demo','collect','--help'],
                     capture_output=True,text=True,timeout=20)
    assert p.returncode==0,p.stderr
    assert '--input-device' in p.stdout and '--spacepilot-map' in p.stdout


def test_spacepilot_cannot_silently_produce_synthetic_demos(tmp_path):
    from omi_hil_rl.hil.demo import collect
    from omi_hil_rl.hil.actor import run_actor
    options=InputOptions(kind='spacepilot')
    with pytest.raises(ValueError,match='transport=ros'):
        collect(tmp_path/'demo',HILConfig(),input_options=options)
    assert not (tmp_path/'demo').exists()
    with pytest.raises(ValueError,match='transport=ros'):
        run_actor(tmp_path/'rl',HILConfig(),input_options=options)


def test_oct17_preset_cli_and_auto_review_guard(tmp_path, monkeypatch):
    from omi_hil_rl.hardware import spacepilot_pose
    dest=tmp_path/'oct17.json'
    result=subprocess.run([sys.executable,str(ROOT/'scripts/configure_spacepilot_hil.py'),
        '--preset','oct17','--start-button-id','12','--output',str(dest)],
        capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    config=HILConfig(review='auto')
    buttons,info=load_button_profile(dest)
    assert buttons=={311:0,315:12,308:23,307:25,314:26,304:28,305:27,FOLLOW_TOGGLE:8,FOLLOW_SAVE:2}
    assert buttons==oct17_buttons(config,12)
    assert 19 not in buttons.values() and 310 not in buttons
    assert info['required_review']=='auto'
    options=InputOptions(kind='spacepilot',profile=dest)
    assert required_buttons(config,314,gripper=True,tag_follow=True,input_options=options)==set(buttons)
    with pytest.raises(ValueError,match='review=auto'):
        create_operator_input(HILConfig(review='manual'),options=options)
    monkeypatch.setattr(spacepilot_pose,'SpaceNav',Driver)
    pad,_,_=create_operator_input(config,options=options)
    assert isinstance(follow_buttons_for_input(pad),DirectFollowButtons)
    pad.close()
    with pytest.raises(ValueError,match='distinct'):
        oct17_buttons(config,23)  # Start cannot reuse the success key.


def test_direct_tag_keys_never_become_gripper_or_episode_events():
    config=HILConfig(review='auto')
    pad=SpacePilotInput(oct17_buttons(config,12),driver_factory=Driver,clock=lambda:1.)
    assert pad.poll()
    selector=follow_buttons_for_input(pad)
    gripper=GripperButtons();episode=ButtonEvents(config)
    selector.select(True,{},());gripper.select(True,{},());episode.poll(True,{},())
    for raw,expected in ((8,'toggle'),(2,'save')):
        pad.driver.events=[(raw,True),(raw,False)]
        pad.poll()
        assert selector.select(True,pad.buttons,pad.button_events)==expected
        assert gripper.select(True,pad.buttons,pad.button_events) is None
        assert episode.poll(True,pad.buttons,pad.button_events)==set()
        assert not ({304,305,310}&{code for code,_,_ in pad.button_events})
        pad.poll()
        assert selector.select(True,pad.buttons,pad.button_events) is None
    for raw,expected in ((28,'close'),(27,'open')):
        pad.driver.events=[(raw,True),(raw,False)];pad.poll()
        assert gripper.select(True,pad.buttons,pad.button_events)==expected
        assert selector.select(True,pad.buttons,pad.button_events) is None
    for raw,role in ((12,'start'),(23,'success'),(25,'manual_stop')):
        pad.driver.events=[(raw,True),(raw,False)];pad.poll()
        assert episode.poll(True,pad.buttons,pad.button_events)=={role}
    pad.driver.events=[(19,True)];pad.poll()
    assert not pad.buttons.get(311)  # old physical3 is no longer takeover
    pad.driver.events=[(0,True)];pad.poll()
    assert pad.buttons[311]
    assert selector.select(True,pad.buttons,pad.button_events)=='stop'


def test_direct_follow_rejects_chords_holds_and_takeover():
    selector=DirectFollowButtons()
    assert selector.select(True,{FOLLOW_TOGGLE:True},[(FOLLOW_TOGGLE,True,True)]) is None
    assert selector.select(True,{},[(FOLLOW_TOGGLE,False,False)]) is None
    assert selector.select(True,{},[(FOLLOW_TOGGLE,True,False),(FOLLOW_TOGGLE,False,False)])=='toggle'
    assert selector.select(True,{FOLLOW_SAVE:True},[(FOLLOW_SAVE,True,False)])=='save'
    assert selector.select(True,{FOLLOW_SAVE:True},[]) is None
    selector.select(True,{},[(FOLLOW_SAVE,False,False)])
    assert selector.select(True,{},[(FOLLOW_TOGGLE,True,False),(FOLLOW_SAVE,True,False),
                                   (FOLLOW_TOGGLE,False,False),(FOLLOW_SAVE,False,False)]) is None
    assert selector.select(True,{311:True,FOLLOW_TOGGLE:True},
                           [(311,True,False),(FOLLOW_TOGGLE,True,False)])=='stop'
    assert selector.select(False,{},[])=='stop'


def test_incomplete_direct_follow_profile_rejected(tmp_path):
    buttons=dict(BUTTONS);buttons[FOLLOW_TOGGLE]=8
    with pytest.raises(ValueError,match='Both direct'):
        load_button_profile(profile(tmp_path,buttons))


def test_hil_scale_aliases_and_requested_cli_defaults():
    parser=argparse.ArgumentParser();add_input_arguments(parser)
    default=options_from_args(parser.parse_args([]))
    assert default.kind=='gamepad'  # input default remains unchanged
    assert (default.translation_scale,default.rotation_scale)==(1.5,.3)
    for prefix in ('','spacepilot-'):
        args=parser.parse_args(['--input-device','spacepilot',f'--{prefix}translation-scale','1.2',
                               f'--{prefix}rotation-scale','0.2'])
        options=options_from_args(args)
        assert (options.translation_scale,options.rotation_scale)==(1.2,.2)


def test_navigation_icon_buttons_do_not_change_six_axis_mapping():
    config=HILConfig(review='auto')
    pad=SpacePilotInput(oct17_buttons(config,12),driver_factory=Driver,clock=lambda:1.)
    mapping=SpacePilotHILMapping(config,InputOptions(kind='spacepilot',translation_scale=1.5,rotation_scale=.3))
    pad.driver.raw=[100,110,120,130,140,150]
    pad.poll()
    before=mapping.action(pad.axes)
    assert np.count_nonzero(before)==6
    for raw in (26,27,28):
        pad.driver.events=[(raw,True),(raw,False)];pad.poll()
        np.testing.assert_array_equal(mapping.action(pad.axes),before)
    assert mapping.mapping.mode=='all' and not mapping.mapping.dominant
