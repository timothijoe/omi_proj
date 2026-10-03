import json
from pathlib import Path
from types import SimpleNamespace as Obj

import numpy as np
import pytest

from omi_hil_rl.training.bag_bc_data import (
    ARRAYS, COMMAND, CONTRACT, KEYS, TOPICS, NotReady, ObservationBuffer,
    decode, digest, export, pool_field, sha256,
)


def fill(buf, timestamp=10**9):
    for key in KEYS:
        if key == "rgb":v=np.zeros((3,128,128),dtype=np.uint8)
        elif key == "q":v=np.zeros(7,dtype=np.float32)
        elif key.endswith("force"):v=np.zeros(6,dtype=np.float32)
        else:v=np.zeros((1 if key.endswith("depth") else 2,16,24),dtype=np.float32)
        buf.add(key,timestamp,v)


def test_pool_keeps_signed_components_and_block_mean():
    value=np.zeros((288,384,2),dtype=np.float32)
    value[...,0]=-2
    value[:18,:16,1]=4
    out=pool_field(value)
    assert out.shape==(2,16,24)
    assert np.all(out[0]==-2)
    assert out[1,0,0]==4 and out[1].sum()==4
    with pytest.raises(ValueError):pool_field(np.zeros((270,360)))


def test_causal_buffer_stale_reset_watermark_and_no_action_input():
    assert COMMAND not in TOPICS
    b=ObservationBuffer()
    with pytest.raises(NotReady):b.at(10**9)
    fill(b)
    data,stamps=b.at(10**9)
    assert data['rgb'].shape==(3,128,128) and data['tactile'].shape==(10,16,24)
    assert data['state'].shape==(19,)
    before=digest(data)
    b.add('q',2*10**9,np.ones(7,dtype=np.float32))
    assert digest(b.at(10**9)[0])==before  # no future joint feedback
    assert digest(b.at(10**9,stamps)[0])==before
    with pytest.raises(NotReady):b.at(1_250_000_001)
    with pytest.raises(ValueError):b.add('q',10**9,np.ones(7))
    b.clear()
    with pytest.raises(NotReady):b.at(2*10**9)
    fill(b,3*10**9)
    with pytest.raises(NotReady):b.at(3*10**9,stamps)  # no previous-loop replacement


def test_reject_nonfinite_and_invalid_decode():
    b=ObservationBuffer()
    with pytest.raises(ValueError):b.add('q',10**9,np.array([np.nan]))
    msg=Obj(header=Obj(stamp=Obj(sec=1,nanosec=0)),arm_positions=[.1]*7)
    with pytest.raises(ValueError):decode('q',msg)
    with pytest.raises(ValueError):export('not_opened','not_created')


def test_bounded_histories():
    b=ObservationBuffer()
    for i in range(1000):b.add('q',i+1,np.zeros(7))
    assert len(b.data['q'])==128


def dataset(path):
    path.mkdir()
    rng=np.random.default_rng(7)
    state=rng.normal(size=(12,19)).astype(np.float32)*.1
    arrays=dict(rgb=rng.integers(0,256,(12,3,128,128),dtype=np.uint8),
                tactile=rng.normal(size=(12,10,16,24)).astype(np.float32)*.1,
                state=state,action=state[:,:7]+.02)
    np.savez_compressed(path/'samples.npz',**arrays)
    (path/'manifest.json').write_text(json.dumps(dict(contract=CONTRACT,samples_sha256=sha256(path/'samples.npz'),episode_id='same_episode')))
    return arrays


def test_real_bc_training_reload_and_no_episode_leakage(tmp_path):
    pytest.importorskip('torch')
    from omi_hil_rl.training.bc_policy import train,load_policy,predict,load_dataset
    data=dataset(tmp_path/'train')
    dataset(tmp_path/'duplicate')
    with pytest.raises(ValueError):train([tmp_path/'train'],tmp_path/'missing_validation',steps=1)
    with pytest.raises(ValueError):train([tmp_path/'train'],tmp_path/'leak',val_paths=[tmp_path/'duplicate'],steps=1)
    with pytest.raises(ValueError):load_dataset([tmp_path/'train',tmp_path/'duplicate'])
    result=train([tmp_path/'train'],tmp_path/'run',overfit=True,steps=30)
    assert result['mode']=='overfit_smoke_not_generalization' and result['validation'] is None
    assert result['final']['rmse_rad']<result['initial']['rmse_rad']
    model,norm,cp=load_policy(tmp_path/'run/policy.pt')
    prediction=predict(model,norm,data)
    assert prediction.shape==(12,7) and np.isfinite(prediction).all()
    with np.load(tmp_path/'run/train_predictions.npz') as saved:
        np.testing.assert_array_equal(prediction,saved['prediction'])
    with pytest.raises(FileExistsError):train([tmp_path/'train'],tmp_path/'run',overfit=True,steps=1)


def test_shadow_safety_and_isolation(monkeypatch):
    from omi_hil_rl.training.bc_shadow import validate_isolation
    monkeypatch.setenv('ROS_DOMAIN_ID','0')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY','1')
    with pytest.raises(ValueError):validate_isolation()
    monkeypatch.setenv('ROS_DOMAIN_ID','99')
    validate_isolation()
    root=Path(__file__).resolve().parents[1]
    text=(root/'src/omi_hil_rl/training/bc_shadow.py').read_text()
    assert 'NS+"/prediction"' in text and 'JointcmdArm' not in text


def test_held_out_validation_uses_train_statistics(tmp_path):
    pytest.importorskip('torch')
    from omi_hil_rl.training.bc_policy import train,normalization
    data=dataset(tmp_path/'train')
    val=dataset(tmp_path/'val')
    val['state']+=20
    val['action']+=20
    np.savez_compressed(tmp_path/'val/samples.npz',**val)
    m=json.loads((tmp_path/'val/manifest.json').read_text())
    m.update(episode_id='distinct_synthetic_episode',samples_sha256=sha256(tmp_path/'val/samples.npz'))
    (tmp_path/'val/manifest.json').write_text(json.dumps(m))
    result=train([tmp_path/'train'],tmp_path/'run',val_paths=[tmp_path/'val'],steps=2)
    assert result['mode']=='episode_held_out' and result['validation_samples']==12
    assert result['normalization']==normalization(data)
