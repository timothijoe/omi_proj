import sys
from pathlib import Path
import uuid
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'ros2/omi_sensors'))
from omi_sensors.wrist_wire import HEADER, Reassembler

SESSION = uuid.UUID('00000000-0000-0000-0000-000000000001')

def packet(fid=1, idx=0, count=1, payload=b'ab', size=2):
    return HEADER.pack(b'FCP1',1,SESSION.bytes,fid,1.,size,idx,count,len(payload),1,0)+payload

def test_reordered_and_duplicates():
    r=Reassembler(str(SESSION))
    assert r.push(packet(idx=1,count=2,payload=b'b'),0) is None
    assert r.push(packet(idx=0,count=2,payload=b'a'),.01)==(1,1.,b'ab')
    assert r.push(packet(),.02) is None

def test_expiry_and_bound():
    r=Reassembler(str(SESSION))
    for i in range(8): r.push(packet(fid=i,count=2,payload=b'a'),0)
    assert len(r.frames)==4
    r.push(packet(fid=20,count=2,payload=b'a'),1)
    assert len(r.frames)==1

def test_bad_packets_and_session():
    r=Reassembler(str(SESSION))
    with pytest.raises(ValueError): r.push(b'bad')
    with pytest.raises(ValueError): r.push(packet(size=10**8))
    with pytest.raises(ValueError): r.push(packet(size=1))
    assert Reassembler(str(uuid.uuid4())).push(packet()) is None
