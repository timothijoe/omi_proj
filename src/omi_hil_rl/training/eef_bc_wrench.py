"""Fixed-size optional wrench inputs; masks describe numeric usability, not calibration."""
from collections import deque
import hashlib
import numpy as np
from .eef_bc_grid import GridProfile
from omi_hil_rl.real.ros_topics import wrench_value

VERSION='bag-eef-bc-v4-wrench'


def enabled_array(value):
    value=np.asarray(value,dtype=np.float32)
    if value.shape!=(2,) or not np.isin(value,[0,1]).all():
        raise ValueError('wrench_enabled must be two binary values')
    return value.copy()


class WrenchBank:
    def __init__(self,enabled=(0,0),max_age_ns=250_000_000):
        self.enabled=enabled_array(enabled);self.max_age_ns=max_age_ns
        self.data=[deque(maxlen=128),deque(maxlen=128)]

    def add(self,side,timestamp,value,valid=True):
        if side not in (0,1) or timestamp<=0:raise ValueError('Invalid wrench side/time')
        v=np.asarray(value,dtype=np.float32)
        usable=bool(valid) and v.shape==(6,) and bool(np.isfinite(v).all())
        if not usable:v=np.zeros(6,np.float32)
        q=self.data[side]
        if q and timestamp<q[-1][0]:raise ValueError('Backward wrench receive time')
        if q and timestamp==q[-1][0]:q.pop()
        q.append((int(timestamp),v.copy(),usable))

    def at(self,reference,expected=None):
        values=np.zeros((2,6),np.float32);mask=np.zeros(2,np.float32);stamps=[0,0];reasons=[]
        for side,q in enumerate(self.data):
            wanted=None if expected is None else expected[side]
            item=next((x for x in reversed(q) if x[0]<=reference and (wanted is None or x[0]==wanted)),None)
            if not self.enabled[side]:reason='disabled'
            elif item is None:reason='missing'
            elif reference-item[0]>self.max_age_ns:reason='stale'
            elif not item[2]:reason='invalid'
            else:reason='valid';values[side]=item[1];mask[side]=1
            # Keep invalid/stale selected source identity for audit and replay.
            if item is not None and self.enabled[side]:stamps[side]=item[0]
            reasons.append(reason)
        return dict(wrench=values.reshape(12),wrench_mask=mask,wrench_enabled=self.enabled.copy()),stamps,reasons


class WrenchProfile(GridProfile):
    ARRAYS=(*GridProfile.ARRAYS,'wrench','wrench_mask','wrench_enabled')

    def __init__(self,mode='optional',enabled=(0,0)):
        super().__init__(mode)
        self.enabled=enabled_array(enabled)
        self.CONTRACT.update(version=VERSION,wrench_shape=[12],wrench_mask_shape=[2],wrench_enabled_shape=[2],
            wrench_order='a_Fxyz_Txyz,b_Fxyz_Txyz',wrench='fixed12; zero if disabled/missing/stale/nonfinite/declared_invalid',
            wrench_mask='per-side enabled AND finite AND receive-fresh AND source-valid; NOT physical calibration',
            wrench_configuration='per-recording/runtime enabled[2], may differ across compatible datasets',
            wrench_normalization='valid training values only; zero masked channels again after normalization',
            deployment='history online shadow interface; no hardware executor')
        self.TOPICS.update({f'/omi/tactile_grid24x16/{s}/wrench':f'{s}_wrench' for s in 'ab'})
        self.KEYS=(*self.KEYS,'a_wrench','b_wrench')

    def decode(self,key,message):
        if not key.endswith('_wrench'):return super().decode(key,message)
        try:value=np.asarray(wrench_value(message),np.float32)
        except ValueError:value=np.full(6,np.nan,np.float32)
        valid=bool(np.isfinite(value).all()) and value.shape==(6,)
        stamp=int(message.header.stamp.sec)*10**9+int(message.header.stamp.nanosec)
        return stamp,np.r_[value if valid else np.zeros(6),float(valid)].astype(np.float32)

    @staticmethod
    def digest(observation):
        h=hashlib.sha256()
        for key in WrenchProfile.ARRAYS:
            a=np.ascontiguousarray(observation[key]);h.update(key.encode()+str(a.shape).encode()+a.dtype.str.encode()+a.tobytes())
        return h.hexdigest()

    def ObservationBuffer(self):return WrenchBuffer(self)


class WrenchBuffer:
    def __init__(self,profile):self.profile=profile;self.clear()

    def clear(self):
        self.base=GridProfile(self.profile.mode).ObservationBuffer()
        self.bank=WrenchBank(self.profile.enabled,self.profile.CONTRACT['max_age_ns'])

    def add(self,key,timestamp,value):
        if key.endswith('_wrench'):
            self.bank.add(0 if key=='a_wrench' else 1,timestamp,value[:6],valid=bool(value[6]))
        else:self.base.add(key,timestamp,value)

    def at(self,reference,expected=None):
        obs,stamps=self.base.at(reference,expected)
        desired=None if expected is None else [expected[k] for k in ('a_wrench','b_wrench')]
        wr,ws,_=self.bank.at(reference,desired);obs.update(wr)
        stamps.update(zip(('a_wrench','b_wrench'),ws))
        return obs,stamps


def validate_wrench(data):
    n=len(data['state']);w=data['wrench'];mask=data['wrench_mask'];enabled=data['wrench_enabled']
    if w.shape!=(n,12) or w.dtype!=np.float32 or not np.isfinite(w).all():raise ValueError('Invalid wrench array')
    for value in (mask,enabled):
        if value.shape!=(n,2) or value.dtype!=np.float32 or not np.isin(value,[0,1]).all():raise ValueError('Invalid wrench mask/enabled')
    if np.any(mask>enabled) or np.any(w.reshape(n,2,6)[mask==0]):raise ValueError('Disabled/invalid wrench must be zero')
