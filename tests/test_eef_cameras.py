import json
from types import SimpleNamespace as Obj
import numpy as np
import pytest
from omi_hil_rl.training import eef_bc_data as single
from omi_hil_rl.training.eef_bc_sources import CameraBuffer, CameraProfile, contract_for, decode, digest, WRIST_TOPIC


def fill_base(buf,t):
    for key in single.legacy.KEYS:
        if key=='rgb':value=np.zeros((3,128,128),np.uint8)
        elif key=='q':value=np.zeros(7,np.float32)
        elif key.endswith('force'):value=np.zeros(6,np.float32)
        else:value=np.zeros((1 if key.endswith('depth') else 2,16,24),np.float32)
        buf.add(key,t,value)
    buf.add('eef',t,np.array([0.,0.,0.,0.,0.,0.,1.]))


def test_optional_causal_selection_absence_expiry_and_watermark():
    b=CameraBuffer('optional'); t=10**9; fill_base(b,t)
    obs,empty=b.at(t)
    assert obs['camera_mask'].tolist()==[1.,0.] and not obs['wrist_rgb'].any()
    assert empty['wrist_rgb']==0
    image=np.full((3,128,128),127,np.uint8)
    b.add('wrist_rgb',t+1,image)
    assert b.at(t)[0]['camera_mask'][1]==0  # future cannot enter input
    obs,stamps=b.at(t+1)
    assert obs['camera_mask'].tolist()==[1.,1.]
    # An offline absence stays absent even if DDS already delivered a future item.
    assert b.at(t+1,empty)[0]['camera_mask'][1]==0
    b.clear(); fill_base(b,t)
    with pytest.raises(single.NotReady):b.at(t+1,stamps)  # await exact wrist watermark
    b.add('wrist_rgb',t+1,image)
    assert digest(b.at(t+1,stamps)[0])==digest(obs)
    fill_base(b,t+250_000_002)
    assert b.at(t+250_000_002)[0]['camera_mask'][1]==0
    b.clear();fill_base(b,t+2*10**9)
    assert b.at(t+2*10**9)[0]['camera_mask'][1]==0


def test_required_off_and_corrupt_wrist():
    t=10**9;b=CameraBuffer('required');fill_base(b,t)
    with pytest.raises(single.NotReady):b.at(t)
    b.add('wrist_rgb',t,np.zeros((3,128,128),np.uint8))
    assert b.at(t)[0]['camera_mask'][1]==1  # valid black image != unavailable image
    fill_base(b,t+250_000_001)
    with pytest.raises(single.NotReady):b.at(t+250_000_001)
    off=CameraBuffer('off');fill_base(off,t)
    assert off.at(t)[0]['camera_mask'].tolist()==[1.,0.]
    assert WRIST_TOPIC not in CameraProfile('off').TOPICS
    with pytest.raises(ValueError):off.add('wrist_rgb',t,np.zeros((3,128,128),np.uint8))
    with pytest.raises(ValueError):b.add('wrist_rgb',t-1,np.zeros((3,128,128),np.uint8))
    with pytest.raises(ValueError):b.add('wrist_rgb',t+1,np.zeros((128,128,3),np.uint8))
    for i in range(200):b.add('wrist_rgb',t+i,np.zeros((3,128,128),np.uint8))
    assert len(b.wrist)==128


def test_wrist_bgr_to_rgb_uses_existing_roi_nearest():
    from omi_hil_rl.real.observation import ObservationConfig,_crop_square_resize_nearest
    yy,xx=np.indices((1080,1920))
    bgr=np.stack((xx%256,yy%256,(xx+yy)%256),axis=-1).astype(np.uint8)
    msg=Obj(height=1080,width=1920,step=1920*3,encoding='bgr8',data=bgr.tobytes(),
            header=Obj(stamp=Obj(sec=1,nanosec=4)))
    timestamp,result=decode('wrist_rgb',msg)
    expected,roi=_crop_square_resize_nearest(bgr[...,::-1],ObservationConfig().wrist_rgb_roi,(128,128))
    assert timestamp==1_000_000_004 and roi==(766,566,389)
    assert result.shape==(3,128,128) and result.dtype==np.uint8
    np.testing.assert_array_equal(result,expected.transpose(2,0,1))


def test_profile_rejects_unknown_contract_and_masks_participate_in_digest():
    assert single.profile_for(single.CONTRACT) is single
    for mode in ('off','required','optional'):
        profile=single.profile_for(contract_for(mode))
        assert profile.mode==mode and profile.CONTRACT['state_shape']==[26]
    invalid=contract_for('optional');invalid['wrist_rgb_roi'][0]=.2
    with pytest.raises(ValueError):single.profile_for(invalid)
    with pytest.raises(ValueError):contract_for('guess')
    b=CameraBuffer('optional');fill_base(b,10**9)
    obs,_=b.at(10**9);original=digest(obs)
    obs['camera_mask'][1]=1
    assert digest(obs)!=original
    before=digest(obs);obs['wrist_rgb'][0,0,0]=1
    assert digest(obs)!=before


def test_replay_topic_whitelist_optional_missing_and_no_control():
    from omi_hil_rl.training.bc_shadow import validate_replay_topics
    base=set(single.TOPICS)
    validate_replay_topics(CameraProfile('optional'),dict(replay_topics=list(base)),base)
    with pytest.raises(ValueError):validate_replay_topics(CameraProfile('required'),dict(replay_topics=list(base)),base)
    with pytest.raises(ValueError):validate_replay_topics(CameraProfile('off'),dict(replay_topics=list(base|{WRIST_TOPIC})),base|{WRIST_TOPIC})
    with pytest.raises(ValueError):validate_replay_topics(CameraProfile('optional'),{},base|{'/tj/control/joint_cmd_A'})


def make_dataset(path,mode='optional',identity='one'):
    path.mkdir();rng=np.random.default_rng(5);n=12
    state=rng.normal(size=(n,26)).astype(np.float32)*.1;state[:,-7:]=[0,0,0,0,0,0,1]
    data=dict(rgb=rng.integers(0,256,(n,3,128,128),dtype=np.uint8),
        wrist_rgb=rng.integers(0,256,(n,3,128,128),dtype=np.uint8),
        camera_mask=np.ones((n,2),np.float32),state=state,
        tactile=rng.normal(size=(n,10,16,24)).astype(np.float32)*.1,
        action=rng.normal(size=(n,6)).astype(np.float32)*.003)
    if mode=='off':data['camera_mask'][:,1]=0;data['wrist_rgb'][:]=0
    if mode=='optional':data['camera_mask'][::2,1]=0;data['wrist_rgb'][::2]=0
    np.savez_compressed(path/'samples.npz',**data)
    (path/'manifest.json').write_text(json.dumps(dict(contract=contract_for(mode),episode_id=identity,
        samples_sha256=single.sha256(path/'samples.npz'))))
    return data


def test_gate_excludes_disabled_encoder_and_gradients_use_enabled_camera():
    torch=pytest.importorskip('torch')
    from omi_hil_rl.training.eef_bc_policy import Policy
    torch.manual_seed(2);torch.set_num_threads(2)
    model=Policy(contract_for('optional'));model.eval()
    rgb=torch.rand(2,3,128,128);touch=torch.rand(2,10,16,24);state=torch.rand(2,26)
    wrist=torch.rand_like(rgb);mask=torch.tensor([[1.,0.],[1.,1.]])
    first=model(rgb,touch,state,wrist,mask)
    changed=wrist.clone();changed[0]*=10
    torch.testing.assert_close(first,model(rgb,touch,state,changed,mask),rtol=0,atol=0)
    first.sum().backward()
    assert model.wrist[0].weight.grad.abs().sum()>0
    assert model.wrist[0].weight.data_ptr()!=model.rgb[0].weight.data_ptr()
    all_off=torch.tensor([[1.,0.],[1.,0.]])
    calls=[]
    handle=model.wrist.register_forward_hook(lambda *args:calls.append(1))
    model(rgb,touch,state,wrist,all_off);handle.remove()
    assert not calls
    with pytest.raises(ValueError):model(rgb,touch,state)


def test_v2_training_reload_and_contract_rejection(tmp_path):
    pytest.importorskip('torch')
    from omi_hil_rl.training import eef_bc_policy as p
    data=make_dataset(tmp_path/'train');make_dataset(tmp_path/'off','off','two')
    with pytest.raises(ValueError):p.load_dataset([tmp_path/'train',tmp_path/'off'])
    with pytest.raises(ValueError):p.train([tmp_path/'train'],tmp_path/'mismatch',val_paths=[tmp_path/'off'],steps=1)
    result=p.train([tmp_path/'train'],tmp_path/'model',overfit=True,steps=40)
    assert result['final']['translation_rmse_m']<result['initial']['translation_rmse_m']
    model,norm,cp=p.load_policy(tmp_path/'model/policy.pt')
    assert model.dual_camera and cp['contract']==contract_for('optional')
    with np.load(tmp_path/'model/train_predictions.npz') as saved:
        np.testing.assert_array_equal(p.predict(model,norm,data),saved['prediction'])
    bad={**data,'camera_mask':data['camera_mask'].copy()};bad['camera_mask'][0,0]=0
    with pytest.raises(ValueError):p.predict(model,norm,bad)
    bad={**data,'wrist_rgb':data['wrist_rgb'].copy()};bad['wrist_rgb'][0]=1
    with pytest.raises(ValueError):p.predict(model,norm,bad)
    with pytest.raises(ValueError):p.validate_cameras(data,contract_for('required'))


def test_selected_replay_preserves_original_payloads_and_receive_times(monkeypatch, tmp_path):
    import sys
    events=[('rgb',b'original-image-cdr',11),('eef',b'pose-cdr-1',12),
            ('eef',b'pose-cdr-2',13),('rgb',b'next-image-cdr',14)]
    written=[]
    class Reader:
        def __init__(self):self.index=0
        def get_all_topics_and_types(self):return ['rgb-meta','eef-meta']
        def has_next(self):return self.index<len(events)
        def read_next(self):
            event=events[self.index];self.index+=1;return event
    class Writer:
        def open(self,*args):pass
        def create_topic(self,meta):pass
        def write(self,*event):written.append(event)
    monkeypatch.setattr(single,'reader',lambda path:Reader())
    monkeypatch.setitem(sys.modules,'rosbag2_py',Obj(SequentialWriter=Writer,
        StorageOptions=lambda **kw:kw,ConverterOptions=lambda *args:args))
    counts=single.write_selected_replay('source',tmp_path/'out',{('rgb',11),('eef',13)})
    assert written==[events[0],events[2]] and counts=={'rgb':1,'eef':1}
    with pytest.raises(ValueError,match='missing'):
        single.write_selected_replay('source',tmp_path/'other',{('eef',999)})
