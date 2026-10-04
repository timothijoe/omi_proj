import importlib.util
from pathlib import Path
import pytest
import ast
import math
import types

# Load only the pure trajectory function; the standalone sender imports ROS like axis_test.
source=(Path(__file__).parents[1]/'scripts/circle_test.py').read_text()
tree=ast.parse(source)
nodes=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name=='circle']
m=types.SimpleNamespace(PLANES={'xy':(0,1),'xz':(0,2),'yz':(1,2)},norm=lambda v:math.sqrt(sum(x*x for x in v)))
namespace={'math':math,'PLANES':m.PLANES}
exec(compile(ast.Module(body=nodes,type_ignores=[]),'<circle>','exec'),namespace)
m.circle=namespace['circle']

@pytest.mark.parametrize('plane',['xy','xz','yz'])
@pytest.mark.parametrize('clockwise',[False,True])
def test_circle_geometry_and_integrated_actions(plane,clockwise):
    points,actions=m.circle(plane=plane,clockwise=clockwise)
    a,b=m.PLANES[plane];other=({0,1,2}-{a,b}).pop()
    assert len(actions)==400
    position=[0.,0.,0.]
    for p,delta in zip(points[1:],actions):
        assert abs((p[a]+30)**2+p[b]**2-900)<1e-9
        assert p[other]==0
        assert delta[3:]==[0.,0.,0.]
        assert m.norm(delta[:3])<1
        position=[position[k]+delta[k] for k in range(3)]
        assert m.norm([position[k]-p[k] for k in range(3)])<1e-10
    assert m.norm(position)<1e-10
    assert actions[0][b]*( -1 if clockwise else 1)>0
    assert m.norm(actions[0][:3])<m.norm(actions[200][:3])
