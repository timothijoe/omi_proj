"""Recorded small tactile grids + already cropped wrist ROI, recorder-time alignment."""
from collections import deque
import numpy as np
from . import eef_bc_data as base
from .eef_bc_sources import ARRAYS, digest, contract_for
from omi_hil_rl.real.ros_topics import decode_image_message


class GridProfile:
    ARRAYS = ARRAYS
    digest = staticmethod(digest)

    def __init__(self, mode='optional'):
        self.mode = mode
        self.CONTRACT = contract_for(mode)
        self.CONTRACT.update(version='bag-eef-bc-v3-grid-receive', state_shape=[14],
            state_order='q_left_7,eef_xyz_xyzw', wrench='excluded; absent streams are not zero measurements',
            wrist_topic='/omi/wrist/color/image_roi',
            wrist_preprocessing='already cropped 128x128 ROI; BGR to RGB only; no second crop',
            tactile_preprocessing='recorded float32 16x24 grid; no second pooling',
            alignment_clock='bag_receive_time_for_all_inputs_and_future_eef_labels',
            ingress_max_header_ahead_ns=100_000_000,
            ingress_header_age_guard='reject receive-header > max_age (EEF 50ms, other 250ms), or header ahead >100ms; no offset correction',
            source_clock='original headers preserved; cross-host offset uncalibrated',
            deployment='offline_only; online source-clock profile not compatible')
        self.TOPICS = {'/camera/camera/color/image_raw': 'rgb', '/tj/info/joint_feedback': 'q'}
        self.TOPICS.update({f'/omi/tactile_grid24x16/{side}/{field}': f'{side}_{field}'
                           for side in 'ab' for field in ('deformation', 'shear', 'depth')})
        self.TOPICS['/tj/info/eef_left'] = 'eef'
        self.REQUIRED_TOPICS = set(self.TOPICS)
        if mode != 'off':
            self.TOPICS['/omi/wrist/color/image_roi'] = 'wrist_rgb'
        if mode == 'required': self.REQUIRED_TOPICS.add('/omi/wrist/color/image_roi')
        self.KEYS = (*[k for k in self.TOPICS.values() if k != 'wrist_rgb'], 'wrist_rgb')

    def decode(self, key, message):
        if key in ('rgb', 'q', 'eef'):
            return base.decode(key, message)
        value = decode_image_message(message)
        if key == 'wrist_rgb':
            if value.shape != (128,128,3) or value.dtype != np.uint8:
                raise ValueError('Expected pre-cropped uint8 wrist ROI 128x128x3')
            value = value.transpose(2,0,1).copy()
        else:
            shape = (16,24) if key.endswith('depth') else (16,24,2)
            if value.shape != shape or value.dtype.kind != 'f' or not np.isfinite(value).all():
                raise ValueError('Expected finite recorded tactile grid ' + str(shape))
            value = value[None] if value.ndim == 2 else value.transpose(2,0,1)
            value = value.astype(np.float32, copy=True)
        return base.legacy.stamp(message), value

    def ObservationBuffer(self):
        return GridBuffer(self)


class GridBuffer:
    def __init__(self, profile):
        self.profile = profile
        self.clear()

    def clear(self):
        self.data = {key: deque(maxlen=128) for key in self.profile.KEYS}

    def add(self, key, timestamp, value):
        items = self.data[key]
        if timestamp <= 0 or not np.isfinite(value).all() or (items and timestamp < items[-1][0]):
            raise ValueError('Invalid/nonmonotonic recorder-time observation')
        if items and items[-1][0] == timestamp: items.pop()
        items.append((timestamp, value))

    def at(self, reference, expected=None):
        values, stamps = {}, {}
        for key, items in self.data.items():
            wanted = None if expected is None else expected[key]
            item = next((x for x in reversed(items) if x[0] <= reference and (wanted is None or x[0] == wanted)), None)
            age = self.profile.CONTRACT['eef_max_age_ns'] if key == 'eef' else self.profile.CONTRACT['max_age_ns']
            if key == 'wrist_rgb' and (self.profile.mode == 'off' or wanted == 0): item = None
            if item is not None and reference-item[0] > age: item = None
            if item is None:
                if key == 'wrist_rgb' and self.profile.mode != 'required' and not wanted:
                    values[key] = np.zeros((3,128,128), np.uint8); stamps[key] = 0
                    continue
                raise base.NotReady('missing_or_stale:' + key)
            stamps[key], values[key] = item
        return dict(rgb=values['rgb'], wrist_rgb=values['wrist_rgb'],
            camera_mask=np.array([1., float(stamps['wrist_rgb'] > 0)], np.float32),
            tactile=np.concatenate([values[f'{s}_{k}'] for s in 'ab' for k in ('deformation','shear','depth')]),
            state=np.r_[values['q'],values['eef']].astype(np.float32)), stamps
