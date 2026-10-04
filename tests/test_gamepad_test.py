"""Direct teleop never falls back to policy or retains an old movement."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import math
import pytest

spec = importlib.util.spec_from_file_location('direct_gamepad_test', Path(__file__).resolve().parents[1]/'scripts/gamepad_test.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_release_and_disconnect_clear_held_stick():
    pad = SimpleNamespace(poll=lambda: True, buttons={311:True}, axes={4:-1})
    mapping = module.Mapping()
    assert module.command(pad,mapping) == ('human',[1.,0.,0.,0.,0.,0.])
    pad.buttons[311] = False
    assert module.command(pad,mapping) == ('idle',[0.]*6)
    pad.buttons[311] = True
    pad.poll = lambda: False
    assert module.command(pad,mapping) == ('disconnected',[0.]*6)


@pytest.mark.parametrize('hz,scale', [(10,.5),(20,.5),(10,2)])
def test_speed_scale_and_rate(hz,scale):
    pad = SimpleNamespace(poll=lambda: True, buttons={311:True}, axes={4:-1,16:-1})
    mapping = module.Mapping(hz=hz,translation_m_s=.01*scale,rotation_rad_s=math.radians(10)*scale)
    mode,data = module.command(pad,mapping)
    assert mode == 'human'
    assert data == pytest.approx([10*scale/hz,0,0,0,0,10*scale/hz])


@pytest.mark.parametrize('value',['nan','inf','0','-1'])
def test_invalid_scale(value):
    with pytest.raises(module.argparse.ArgumentTypeError):module.positive(value)


def test_installation_wrapper_at_final_output():
    pad=SimpleNamespace(poll=lambda:True,buttons={311:True},axes={3:-1})
    mapping=module.Mapping(translation_m_s=.005)
    mode,data=module.command(pad,mapping,'sdk-x-forward-z-left')
    assert mode=='human'
    assert data==pytest.approx([0,0,.5,0,0,0])
    pad.axes={17:-1}
    assert module.command(pad,mapping,'sdk-x-forward-z-left')[1]==pytest.approx([0,-.5,0,0,0,0])
    pad.buttons[311]=False
    assert module.command(pad,mapping,'sdk-x-forward-z-left')==('idle',[0.]*6)


def test_original_and_final_are_from_one_read():
    calls=[]
    def poll():
        calls.append(1)
        return True
    pad=SimpleNamespace(poll=poll,buttons={311:True},axes={3:-1})
    mode,original,data=module.command_details(pad,module.Mapping(),'sdk-x-forward-z-left')
    assert len(calls)==1
    assert list(original)==pytest.approx([0,.001,0,0,0,0])
    assert data==pytest.approx([0,0,1,0,0,0])
    line=module.format_action_trace(mode,original,'sdk-x-forward-z-left',data)
    assert '原始(mm/deg旋转向量)=[0, 1, 0, 0, 0, 0]' in line
    assert '转换=是' in line and '仅预览' in line
    assert '转换后/最终(mm/degABC)=[0, 0, 1, 0, 0, 0]' in line


@pytest.mark.parametrize('convention,flag,swap',[
    ('legacy','否','否'),('sdk-base-aligned','是','否'),('sdk-x-forward-z-left','是','是')])
def test_trace_describes_operation_even_for_zero_input(convention,flag,swap):
    line=module.format_action_trace('idle',[0.]*6,convention,[0.]*6,True)
    assert f'转换={flag}({convention})' in line
    assert f'换轴={swap}' in line
    assert '已发布' in line
