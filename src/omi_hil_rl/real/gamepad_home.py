"""RB+X Cartesian return, using the receiver's calibrated SDK FK (BASE m/rad)."""
import json
import math
import time

import numpy as np

from .sdk_action import output_action

BTN_X = 308  # Standard positional mapping: left face button, BTN_WEST.
HOME_SERVICE = '/delta_ctrl_node/home_poses'


def add_home_arguments(parser):
    parser.add_argument('--home-button-code', type=int, default=BTN_X,
                        help='Linux code for physical X: standard 308; legacy drivers may use 307')
    parser.add_argument('--home-button-alone', action='store_true',
                        help='Trigger home with the configured button without holding RB')


def pose_delta(current, target):
    current, target = np.asarray(current, dtype=float), np.asarray(target, dtype=float)
    for pose in (current, target):
        if pose.shape != (4, 4) or not np.isfinite(pose).all():
            raise ValueError('Invalid FK pose')
        if (not np.allclose(pose[3], [0, 0, 0, 1]) or
                not np.allclose(pose[:3, :3].T @ pose[:3, :3], np.eye(3), atol=1e-6) or
                not np.isclose(np.linalg.det(pose[:3, :3]), 1, atol=1e-6)):
            raise ValueError('Invalid FK rotation')
    rotation = target[:3, :3] @ current[:3, :3].T
    angle = math.acos(float(np.clip((np.trace(rotation)-1)/2, -1, 1)))
    skew = np.array([rotation[2, 1]-rotation[1, 2], rotation[0, 2]-rotation[2, 0],
                     rotation[1, 0]-rotation[0, 1]])
    if angle < 1e-8:
        rotvec = skew/2
    elif math.pi-angle < 1e-6:
        values, vectors = np.linalg.eigh((rotation+rotation.T)/2)
        axis = vectors[:, np.argmax(values)]
        if np.dot(axis, skew) < 0:
            axis = -axis
        rotvec = axis*angle
    else:
        rotvec = skew * angle/(2*math.sin(angle))
    return np.r_[target[:3, 3]-current[:3, 3], rotvec]


class HomeSteps:
    """Straight translation + shortest BASE rotation; last step has no overshoot."""
    def __init__(self, current, target):
        self.remaining = pose_delta(current, target)

    def step(self):
        translation, rotation = np.linalg.norm(self.remaining[:3]), np.linalg.norm(self.remaining[3:])
        fraction = 1/max(1., translation/.001, rotation/math.radians(1.))
        delta = self.remaining*fraction
        self.remaining -= delta
        return delta

    @property
    def done(self):
        return np.linalg.norm(self.remaining) < 1e-12


class GamepadHome:
    """Asynchronous read-only FK request with configurable RB requirement."""
    def __init__(self, node=None, clock=time.monotonic, button_code=BTN_X,
                 require_rb=True):
        self.clock = clock
        self.button_code = button_code
        self.require_rb = require_rb
        self.client = None
        if node is not None:
            from std_srvs.srv import Trigger
            self.request_type = Trigger.Request
            self.client = node.create_client(Trigger, HOME_SERVICE)
        self.future = self.plan = None
        self.previous_x = True  # require release after startup/reconnect
        self.next_step = 0.
        self.status = ''

    def tick(self, connected, buttons, transitions=()):
        x, rb = bool(buttons.get(self.button_code, False)), bool(buttons.get(311, False))
        rising = False
        if connected:
            for code, pressed, initial in transitions:
                if code == self.button_code:
                    if pressed and not initial and not self.previous_x:
                        rising = True
                    self.previous_x = bool(pressed)
            if x and not self.previous_x:
                rising = True
            self.previous_x = x
        else:
            self.previous_x = True
        if not connected or (self.require_rb and not rb):
            if self.future is not None or self.plan is not None:
                self.status = ('返回已取消：RB 松开或手柄断开' if self.require_rb
                               else '返回已取消：手柄断开')
            if self.future is not None:
                self.future.cancel()
            self.future = self.plan = None
            return None
        now = self.clock()
        if rising and self.future is None and self.plan is None:
            if self.client is None or not self.client.service_is_ready():
                self.status = ('返回失败：FK 服务 '+HOME_SERVICE+
                               ' 不可用；请构建并重启接收端，核对 ROS_DOMAIN_ID')
                return ('home_unavailable', np.zeros(6), [0.]*6)
            self.future = self.client.call_async(self.request_type())
            self.requested_at = now
            self.status = '正在读取当前关节并计算返回位姿'
        if self.future is not None:
            if now-self.requested_at > 1.:
                self.future.cancel()
                self.future = None
                self.status = '返回失败：FK 请求超时'
                return ('home_failed', np.zeros(6), [0.]*6)
            if self.future.done():
                try:
                    result = self.future.result()
                    if not result.success:
                        raise ValueError(result.message)
                    poses = json.loads(result.message)
                    if poses['frame'] != 'sdk_base':
                        raise ValueError('FK frame must be sdk_base')
                    self.plan = HomeSteps(poses['current'], poses['target'])
                    self.next_step = now
                    self.status = '返回中：BASE 增量 1 mm / 10 Hz'
                except Exception as exc:
                    self.status = '返回失败：'+str(exc)
                    self.future = None
                    return ('home_failed', np.zeros(6), [0.]*6)
                self.future = None
            else:
                return ('home_waiting', np.zeros(6), [0.]*6)
        if self.plan is not None:
            delta = np.zeros(6)
            if now >= self.next_step-1e-3:
                delta = self.plan.step()
                self.next_step = now+.1  # no catch-up bursts
                if self.plan.done:
                    self.plan = None
                    self.status = '返回增量发布完成（不代表实测到达）'
            return ('human_home', delta, output_action(delta, 'sdk-base-aligned'))
        return None
