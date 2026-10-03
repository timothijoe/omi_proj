"""Versioned dual-camera selection and explicit per-observation camera masks."""
from __future__ import annotations
from collections import deque
from copy import deepcopy
import hashlib
import numpy as np
from . import eef_bc_data as single
from omi_hil_rl.real.observation import ObservationConfig, _crop_square_resize_nearest
from omi_hil_rl.real.ros_topics import decode_image_message

WRIST_TOPIC = '/tj/dm_camera/camera/color'
MODES = ('off', 'required', 'optional')
ARRAYS = (*single.ARRAYS, 'wrist_rgb', 'camera_mask')


def contract_for(mode):
    if mode not in MODES:
        raise ValueError('Unknown wrist camera mode')
    contract = deepcopy(single.CONTRACT)
    contract.update(version='bag-eef-bc-v2', wrist_camera=mode,
                    wrist_topic=WRIST_TOPIC, wrist_rgb_shape=[3, 128, 128],
                    wrist_rgb_roi=[.500, .704, .36],
                    camera_order=['external', 'wrist'], camera_mask_shape=[2],
                    camera_mask='float32 binary: enabled AND causal fresh frame; external always required',
                    wrist_preprocessing='decode RGB; square ROI; nearest resize; uint8/255',
                    missing_wrist='zero uint8 image and mask=0; required mode rejects',
                    camera_quality='timestamp freshness only; no frozen-image or exposure validation',
                    wrist_training_dropout=.2 if mode == 'optional' else 0.)
    return contract


def digest(observation):
    h = hashlib.sha256()
    for key in ARRAYS:
        array = np.ascontiguousarray(observation[key])
        h.update(key.encode() + str(array.shape).encode() + array.dtype.str.encode())
        h.update(array.tobytes())
    return h.hexdigest()


def decode(key, message):
    if key != 'wrist_rgb':
        return single.decode(key, message)
    image = decode_image_message(message)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('Wrist must decode to uint8 RGB')
    image = _crop_square_resize_nearest(image, ObservationConfig().wrist_rgb_roi, (128, 128))[0]
    return single.legacy.stamp(message), image.transpose(2, 0, 1).copy()


class CameraBuffer(single.ObservationBuffer):
    def __init__(self, mode):
        if mode not in MODES:
            raise ValueError('Unknown wrist camera mode')
        self.mode = mode
        super().__init__()

    def clear(self):
        super().clear()
        self.wrist = deque(maxlen=128)

    def add(self, key, timestamp, value):
        if key != 'wrist_rgb':
            return super().add(key, timestamp, value)
        if self.mode == 'off':
            raise ValueError('Wrist input disabled by contract')
        value = np.asarray(value)
        if value.shape != (3, 128, 128) or value.dtype != np.uint8 or timestamp <= 0:
            raise ValueError('Invalid wrist image/timestamp')
        if self.wrist and timestamp < self.wrist[-1][0]:
            raise ValueError('Backward wrist header; explicit reset required')
        if self.wrist and timestamp == self.wrist[-1][0]:
            self.wrist.pop()
        self.wrist.append((int(timestamp), value.copy()))

    def at(self, reference, expected=None):
        obs, stamps = super().at(reference, expected)
        wanted = None if expected is None else expected['wrist_rgb']
        selected = None
        if self.mode != 'off' and wanted != 0:
            selected = next((v for v in reversed(self.wrist)
                             if v[0] <= reference and (wanted is None or v[0] == wanted)), None)
            if selected is not None and reference - selected[0] > single.CONTRACT['max_age_ns']:
                selected = None
        # A positive watermark must arrive even for optional input; never silently
        # downgrade an offline-present frame because DDS delivered it later.
        if selected is None and (self.mode == 'required' or (wanted is not None and wanted > 0)):
            raise single.NotReady('missing_or_stale:wrist_rgb')
        obs['wrist_rgb'] = np.zeros((3, 128, 128), dtype=np.uint8) if selected is None else selected[1]
        obs['camera_mask'] = np.array([1., float(selected is not None)], dtype=np.float32)
        stamps['wrist_rgb'] = 0 if selected is None else selected[0]
        return obs, stamps


class CameraProfile:
    """Selected once per dataset/checkpoint; no global contract mutations."""
    ARRAYS = ARRAYS
    KEYS = (*single.KEYS, 'wrist_rgb')
    REQUIRED_TOPICS = set(single.TOPICS)
    decode = staticmethod(decode)
    digest = staticmethod(digest)

    def __init__(self, mode):
        self.CONTRACT = contract_for(mode)
        self.TOPICS = dict(single.TOPICS)
        if mode != 'off':
            self.TOPICS[WRIST_TOPIC] = 'wrist_rgb'
        if mode == 'required':
            self.REQUIRED_TOPICS = {*single.TOPICS, WRIST_TOPIC}
        self.mode = mode

    def ObservationBuffer(self):
        return CameraBuffer(self.mode)
