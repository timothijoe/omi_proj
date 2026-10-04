"""Causal receive-time history inference. Produces candidates, never robot commands."""
from collections import OrderedDict
import numpy as np
import torch
from .eef_bc_history import load_history_policy, SLOTS, PERIOD_NS
from .eef_bc_policy import inputs, validate_cameras
from .eef_bc_grid import GridProfile
from .eef_bc_wrench import WrenchProfile, enabled_array, validate_wrench
from .eef_bc_data import NotReady
from .eef_action import check_increment


class OnlineHistoryPolicy:
    """Single-threaded adapter. All timestamps use the receiver's ROS clock.

    ingest(key, message, receive_ns) -> accepted
    step(reference_ns) -> serializable status with optional action[6]
    reset() -> new epoch; clears sources and history
    set_wrench_enabled([a,b]) -> new epoch when configuration changes

    References are on a 100 ms lattice. Missing slots are never compacted.
    """
    def __init__(self, checkpoint, wrench_enabled=(0,0)):
        torch.set_num_threads(2)
        self.model,self.norm,self.checkpoint=load_history_policy(checkpoint)
        self.contract=self.model.encoder.contract
        self.enabled=enabled_array(wrench_enabled)
        self.has_wrench='wrench_shape' in self.contract
        if not self.has_wrench and np.any(self.enabled):
            raise ValueError('Checkpoint was trained without wrench; enabling requires v4 retraining')
        mode=self.contract['wrist_camera']
        self.profile=WrenchProfile(mode,self.enabled) if self.has_wrench else GridProfile(mode)
        if self.profile.CONTRACT!=self.contract:raise ValueError('Unsupported online checkpoint contract')
        self.epoch=-1;self.reset()

    def reset(self):
        self.epoch+=1;self.sequence=0;self.last_reference=None;self.last_receive=None
        self.buffer=self.profile.ObservationBuffer();self.features=OrderedDict()

    def set_wrench_enabled(self,value):
        enabled=enabled_array(value)
        if not self.has_wrench and np.any(enabled):raise ValueError('Checkpoint has no wrench input')
        if not np.array_equal(enabled,self.enabled):
            self.enabled=enabled;self.profile.enabled=enabled.copy();self.reset()

    def ingest(self,key,message,receive_ns,*,source_valid=True):
        if receive_ns<=0:raise ValueError('Positive receive timestamp required')
        if self.last_receive is not None and receive_ns<self.last_receive:self.reset()
        self.last_receive=receive_ns
        stamp,value=self.profile.decode(key,message)
        limit=self.contract['eef_max_age_ns'] if key=='eef' else self.contract['max_age_ns']
        accepted=stamp>0 and -self.contract['ingress_max_header_ahead_ns']<=receive_ns-stamp<=limit
        if key.endswith('_wrench'):
            if not accepted or not source_valid:value=np.zeros(7,np.float32)
            self.buffer.add(key,receive_ns,value)
        elif accepted:self.buffer.add(key,receive_ns,value)
        return accepted

    def step(self,reference_ns):
        if reference_ns<=0:raise ValueError('Positive reference timestamp required')
        if self.last_reference is not None:
            if reference_ns<=self.last_reference:
                self.reset()
            elif (reference_ns-self.last_reference)%PERIOD_NS:
                raise ValueError('Reference must stay on the 100 ms lattice; reset to change phase')
        try:obs,stamps=self.buffer.at(reference_ns)
        except NotReady as exc:return self.push(reference_ns,None,reason=str(exc))
        status=self.push(reference_ns,obs,source_stamps=stamps)
        if self.has_wrench:status['wrench_reasons']=self.buffer.bank.at(reference_ns)[2]
        return status

    def push(self,reference_ns,observation,*,source_stamps=None,reason='missing_current'):
        """Already aligned observation API, also used for deterministic offline replay.

        Caller must apply freshness/causality guards; use ingest/step for ROS streams.
        """
        if reference_ns<=0:raise ValueError('Positive reference timestamp required')
        if self.last_reference is not None:
            if reference_ns<=self.last_reference:raise ValueError('Reset before nonmonotonic push')
            if (reference_ns-self.last_reference)%PERIOD_NS:raise ValueError('Off-grid reference')
        if source_stamps and any(t>reference_ns for t in source_stamps.values()):raise ValueError('Future source')
        self.last_reference=reference_ns;self.sequence+=1
        for t in list(self.features):
            if t<reference_ns-(SLOTS-1)*PERIOD_NS:del self.features[t]
        status=dict(epoch=self.epoch,sequence=self.sequence,reference_ns=int(reference_ns),
            expires_ns=int(reference_ns+PERIOD_NS),valid=False,reason=reason,action=None,
            frame_id=self.contract['frame_id'],action_order=['dx','dy','dz','rx','ry','rz'],
            wrench_enabled=self.enabled.astype(int).tolist(),wrench_mask=[0,0],
            camera_mask=[0,0],checkpoint_contract=self.contract['version'],
            source_stamps=source_stamps or {},history_mask=[False]*SLOTS)
        if observation is not None:
            data={k:np.asarray(observation[k])[None] for k in self.profile.ARRAYS}
            validate_cameras(data,self.contract)
            status['camera_mask']=observation['camera_mask'].astype(int).tolist()
            if self.has_wrench:
                validate_wrench(data)
                if not np.array_equal(observation['wrench_enabled'],self.enabled):
                    raise ValueError('Use set_wrench_enabled before changing configuration')
                status['wrench_mask']=observation['wrench_mask'].astype(int).tolist()
            for k in ('rgb','tactile','state'):
                if list(data[k].shape[1:])!=self.contract[k+'_shape'] or not np.isfinite(data[k]).all():
                    raise ValueError('Invalid observation '+k)
            with torch.inference_mode():self.features[reference_ns]=self.model.encode(inputs(data,self.norm))[0]
        features=torch.zeros(1,SLOTS,128);mask=torch.zeros(1,SLOTS,dtype=torch.bool)
        for j in range(SLOTS):
            t=reference_ns-(SLOTS-1-j)*PERIOD_NS
            if t in self.features:features[0,j]=self.features[t];mask[0,j]=True
        status['history_mask']=mask[0].tolist()
        if observation is None:return status
        with torch.inference_mode():pred=self.model.from_features(features,mask).numpy()[0]
        action=pred*np.asarray(self.norm['delta_std'],np.float32).reshape(6)+np.asarray(self.norm['delta_mean'],np.float32).reshape(6)
        try:check_increment(action,self.contract['max_translation_m'],self.contract['max_rotation_rad'])
        except ValueError as exc:status['reason']='invalid_action:'+str(exc);return status
        status.update(valid=True,reason='ok',action=action.tolist())
        return status
