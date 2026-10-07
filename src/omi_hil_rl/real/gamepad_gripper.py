"""Edge-triggered gamepad gripper control using the local Lingkong SDK."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

BTN_A, BTN_B = 304, 305


def bounded_int(low, high):
    def parse(value):
        try:
            number = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError('Expected an integer') from exc
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f'Expected {low}..{high}')
        return number
    return parse


def add_gripper_arguments(parser):
    parser.add_argument('--gripper-server', help='Enable gripper at HOST:PORT (A close, B open; no RB required)')
    parser.add_argument('--gripper-sdk-root', type=Path, help='Directory containing dm_lingkong_grip_sdk')
    parser.add_argument('--gripper-calibration', type=Path, help='Known limits JSON; no homing is performed')
    parser.add_argument('--gripper-close-speed', type=bounded_int(10, 100), default=50,
                        help='SDK speed 10..100, also used for opening')
    parser.add_argument('--gripper-close-position', type=bounded_int(0, 1000), default=0)
    parser.add_argument('--gripper-close-torque', type=bounded_int(10, 100), default=30,
                        help='Torque limit percent, also used for opening (default 30)')
    parser.add_argument('--gripper-open-position', type=bounded_int(0, 1000), default=1000)


def calibration_from_args(args, parser):
    if not args.gripper_server:
        return None
    if args.gripper_calibration is None:
        parser.error('--gripper-server requires --gripper-calibration')
    try:
        data = json.loads(args.gripper_calibration.read_text())
        required = ('clamp_pos', 'open_pos', 'max_itinerary', 'speed_coe')
        if not isinstance(data, dict) or any(type(data.get(k)) is not int for k in required):
            raise ValueError('calibration requires integer ' + ', '.join(required))
        if data['max_itinerary'] <= 0 or data['speed_coe'] <= 0:
            raise ValueError('max_itinerary and speed_coe must be positive')
        if data['clamp_pos'] - data['open_pos'] != data['max_itinerary']:
            raise ValueError('clamp_pos - open_pos must equal max_itinerary')
        if args.gripper_close_position >= args.gripper_open_position:
            raise ValueError('close position must be below open position')
        return {k: data[k] for k in required}
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))


class GripperButtons:
    def __init__(self):
        self.ready = False
        self.held = {BTN_A: False, BTN_B: False}

    def select(self, connected, buttons, transitions=()):
        a, b = bool(buttons.get(BTN_A)), bool(buttons.get(BTN_B))
        if not connected:
            self.ready = False
            self.held = {BTN_A: False, BTN_B: False}
            return None
        button_transitions = [(code, bool(pressed), initial) for code, pressed, initial in transitions
                              if code in self.held]
        if button_transitions:
            conflict = {code for code, pressed, initial in button_transitions if pressed and not initial} == {BTN_A, BTN_B}
            action = None
            for code, pressed, initial in button_transitions:
                self.held[code] = pressed
                if not any(self.held.values()):
                    self.ready = True
                elif pressed:
                    if not initial and self.ready and not conflict and action is None:
                        action = 'close' if code == BTN_A else 'open'
                    self.ready = False
                else:
                    self.ready = False
            self.held = {BTN_A: a, BTN_B: b}
            self.ready = not a and not b
            return action
        self.held = {BTN_A: a, BTN_B: b}
        if not a and not b:
            self.ready = True
            return None
        ready, self.ready = self.ready, False
        if ready and a != b:
            return 'close' if a else 'open'
        return None


class GamepadGripper:
    def __init__(self, args, calibration, execute, sdk_factory=None):
        self.args, self.calibration, self.execute = args, calibration, execute
        self.factory = sdk_factory
        self.buttons = GripperButtons()
        self.sdk = self.pool = self.pending = None

    def start(self):
        if not self.args.gripper_server:
            return
        print('夹爪：A 闭合，B 张开，无需 RB；松开 A/B 后再按触发一次；'
              f'速度={self.args.gripper_close_speed}，闭合位置={self.args.gripper_close_position}，'
              f'力矩上限={self.args.gripper_close_torque}%；'
              + ('SDK 控制' if self.execute else '仅预览'), flush=True)
        if not self.execute:
            return
        if self.factory is None:
            if self.args.gripper_sdk_root:
                sys.path.insert(0, str(self.args.gripper_sdk_root.resolve()))
            from dm_lingkong_grip_sdk import LingkongGrip
            self.factory = LingkongGrip
        self.sdk = self.factory(server_address=self.args.gripper_server)
        try:
            # Vendor move_to_pos ignores send_can's bool. Propagate transport failures.
            send_can = self.sdk.client.send_can
            def checked_send(*args, **kwargs):
                if send_can(*args, **kwargs) is not True:
                    raise RuntimeError('Gripper CAN send failed')
                return True
            self.sdk.client.send_can = checked_send
            if self.sdk.grip_init_with_known_limits(**self.calibration) is not True:
                raise RuntimeError('Gripper known-limit initialization failed')
            # Set speed once: SDK set_speed can otherwise resend its previous target.
            if self.sdk.set_speed(self.args.gripper_close_speed) is not True:
                raise RuntimeError('Gripper speed rejected')
            self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='gripper')
        except BaseException:
            self.close()
            raise

    def _move(self, position):
        if self.sdk.read_pos() == -1:
            raise RuntimeError('Gripper feedback unavailable or motor fault')
        if self.sdk.set_torque_limit(self.args.gripper_close_torque) is not True:
            raise RuntimeError('Gripper torque rejected')
        if self.sdk.move_to_pos(position) is not True:
            raise RuntimeError('Gripper position rejected')

    def tick(self, connected, buttons, transitions=()):
        if not self.args.gripper_server:
            return None
        if self.pending is not None and self.pending.done():
            self.pending.result()  # fail closed; do not retry an old target
            self.pending = None
        action = self.buttons.select(connected, buttons, transitions)
        if action is None:
            return None
        position = (self.args.gripper_close_position if action == 'close'
                    else self.args.gripper_open_position)
        status = 'preview'
        if self.execute:
            if self.pending is not None:
                status = 'busy_dropped'
            else:
                self.pending = self.pool.submit(self._move, position)
                status = 'submitted'
        row = dict(action=action, position=position, speed=self.args.gripper_close_speed,
                   torque_percent=self.args.gripper_close_torque, status=status)
        print('夹爪 ' + json.dumps(row, ensure_ascii=False), flush=True)
        return row

    def close(self):
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.pool = None
        if self.sdk is not None:
            self.sdk.close(reset_torque=False)
            self.sdk = None
