"""AprilTag perception attached to the actor's existing ROS node (no publisher)."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import sys
import time

import cv2

from .tag_follow import (FollowButtons, FollowButtonFilter, FollowController, TAG_SIZES,
                         load_calibration, load_default, save_default, control_description)
from .tag_follow_camera import ROSCamera


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POSE = ROOT / 'ros2/marker_detect/handeye_result/tag_follow_default.json'


def detector_module():
    name = '_omi_follow_tag_pose'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / 'ros2/marker_detect/tag_pose.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


class TagFollowSession:
    """Main thread owns controller/buttons; one worker owns the estimator only."""
    def __init__(self, node, args):
        self.buttons, self.button_filter = FollowButtons(), FollowButtonFilter()
        self.controller = FollowController()
        self.default_path = args.tag_follow_default_pose
        self.camera = self.pool = self.pending = None
        self.estimator = self.signature = None
        self.last_stamp = float('-inf')
        self.sequence = -1
        self.next_command = 0.
        self.next_log = 0.
        self.error = ''
        try:
            self.controller.default = load_default(self.default_path)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f'TAG_FOLLOW: 默认位姿无效，需重新保存: {exc}', flush=True)
        try:
            self.controller.calibration = load_calibration(args.tag_follow_calibration)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f'TAG_FOLLOW: X/Z 标定不可用，仅支持保存相对位姿: {exc}', flush=True)
        try:
            self.detector = detector_module()
            self.camera = ROSCamera(node, args.tag_follow_image_topic, args.tag_follow_camera_info_topic)
            self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='tag-follow-detect')
        except ImportError as exc:
            self.error = f'标签检测依赖不可用: {exc}'
            print('TAG_FOLLOW: '+self.error, flush=True)
        print('TAG_FOLLOW: LB+305保存，LB+304跟随/停止，RB接管；跟随动作不进入训练回放。'
              f' 默认文件={self.default_path}', flush=True)
        print('TAG_FOLLOW 控制: '+control_description(), flush=True)

    @property
    def active(self):
        return self.controller.active

    def stop(self):
        self.controller.stop()

    def operate(self, action, now):
        if self.error:
            raise ValueError(self.error)
        if action == 'save':
            relative = self.controller.capture(now)
            save_default(self.default_path, relative)
            self.controller.default = relative
            print(f'TAG_FOLLOW: 已保存默认相对位姿 {self.default_path}', flush=True)
        elif action == 'start':
            self.controller.start(now)
            self.next_command = 0.
            print('TAG_FOLLOW: 开始跟随；策略与回合计时暂停', flush=True)

    def _detect(self, frame):
        sequence, image, stamp, received, k, d, frame_id = frame
        signature = (image.shape, k.tobytes(), d.tobytes(), frame_id)
        if signature != self.signature or received <= self.last_stamp:
            self.estimator = self.detector.TagPoseEstimator(
                k, d, TAG_SIZES, family='tag36h11', image_width=image.shape[1], nthreads=2,
                filter_params={10: self.detector.MOVING_TAG_FILTER, 12: self.detector.STATIC_TAG_FILTER},
                depth_mode='off')
            self.signature = signature
        self.last_stamp = received
        observations = self.estimator.process(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), received)
        return observations, received

    def refresh(self):
        if self.camera is None:
            return
        # Never wait for detection in the actor/joystick loop. Keep only latest input.
        if self.pending is not None and self.pending.done():
            try:
                observations, received = self.pending.result()
                self.controller.observe(observations, received)
            except Exception as exc:
                self.controller.observe({}, time.monotonic())
                self.controller.reason = f'detection failed: {exc}'
            self.pending = None
        if self.camera.invalid_reason:
            self.controller.observe({}, time.monotonic())
            self.controller.reason = self.camera.invalid_reason
        frame = self.camera.latest
        if self.pending is None and frame is not None and frame[0] != self.sequence:
            self.sequence = frame[0]
            if 0 <= time.monotonic() - frame[3] < .12:
                self.pending = self.pool.submit(self._detect, frame)

    def command(self, now):
        if not self.active or now < self.next_command:
            return None
        self.next_command = now + .1
        action = self.controller.action(now)
        if now >= self.next_log:
            print('TAG_FOLLOW: '+self.controller.state(now)+
                  f' error(mm/rotvec-deg)={self.controller.error_mm_rotvec_deg.round(3).tolist()}'
                  f' {self.controller.reason}', flush=True)
            self.next_log = now + 1.
        return action

    def close(self):
        self.stop()
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)
