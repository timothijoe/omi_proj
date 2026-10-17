"""Selectable human input for HIL; preserve logical gamepad codes and replay units.

SpacePilot is an input backend, never a second ROS action publisher. Profiles map
confirmed libspnav IDs to logical Linux button codes consumed by existing actors.
"""
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

PROFILE_SCHEMA = 'omi-spacepilot-hil-input-v1'
PROFILE_FRAME = 'X-forward Y-left Z-up'
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE = ROOT / 'local/spacepilot/hil_buttons.json'
# Private logical codes, never emitted as A/B to the gripper or episode reviewer.
FOLLOW_TOGGLE = 65536
FOLLOW_SAVE = 65537
DIRECT_FOLLOW_CODES = {FOLLOW_TOGGLE, FOLLOW_SAVE}


def button_labels(config, home_button_code=314, *, direct_follow=False):
    labels = {}
    def add(code, label):
        if code is not None:
            labels.setdefault(code, []).append(label)
    add(311, '按住人工接管 / 回合外手动移动')
    add(config.start_button, '开始回合 Start')
    add(config.success_button, '成功并结束回合')
    add(config.stop_button, '提前结束回合（非成功）')
    add(home_button_code, '回合外回 home')
    add(304, 'A / 夹爪闭合')
    add(305, 'B / 夹爪张开')
    if direct_follow:
        add(FOLLOW_TOGGLE, '单键开启/停止标签跟随（原LB+A）')
        add(FOLLOW_SAVE, '单键保存标签关系（原LB+B）')
    else:
        add(310, 'LB / 与A切换标签跟随、与B保存标签关系')
    if config.review == 'manual':
        add(config.keep_button, '人工审阅保留')
        add(config.discard_button, '人工审阅丢弃')
    return {code: '；'.join(names) for code, names in labels.items()}


def load_button_profile(path):
    path = Path(path)
    try:
        blob = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError('SpacePilot按键配置不存在：'+str(path)+
                         '；先运行 .venv/bin/python scripts/configure_spacepilot_hil.py') from exc
    profile = json.loads(blob)
    if not isinstance(profile, dict) or profile.get('schema') != PROFILE_SCHEMA or profile.get('axis_frame') != PROFILE_FRAME:
        raise ValueError('Unsupported SpacePilot button profile schema/frame')
    entries = profile.get('buttons')
    if not isinstance(entries, dict) or not entries:
        raise ValueError('SpacePilot profile requires buttons: logical-code -> device-ID')
    mapping = {}
    for code, raw in entries.items():
        if (not isinstance(code, str) or not code.isdecimal() or str(int(code)) != code
                or type(raw) is not int or not 0 <= raw < 256):
            raise ValueError('Button profile requires canonical integer code keys and IDs in [0,256)')
        mapping[int(code)] = raw
    if 311 not in mapping or len(set(mapping.values())) != len(mapping):
        raise ValueError('Profile requires takeover code 311 and distinct physical button IDs')
    if DIRECT_FOLLOW_CODES & set(mapping) and not DIRECT_FOLLOW_CODES <= set(mapping):
        raise ValueError('Both direct tag-follow buttons must be configured together')
    required_review = profile.get('required_review')
    if required_review not in (None, 'auto'):
        raise ValueError('Unsupported required_review in SpacePilot profile')
    return mapping, dict(kind='spacepilot', profile=str(path.resolve()),
                         profile_sha256=hashlib.sha256(blob).hexdigest(),
                         buttons={str(k): v for k, v in mapping.items()}, axis_frame=PROFILE_FRAME,
                         required_review=required_review)


def oct17_buttons(config, start_button_id, home_button_code=314):
    """User-selected layout. Start's physical ID must be explicitly measured."""
    if config.review != 'auto':
        raise ValueError('October 17 layout requires review=auto')
    codes = [311, config.start_button, config.success_button, config.stop_button,
             home_button_code, 304, 305, FOLLOW_TOGGLE, FOLLOW_SAVE]
    ids = [0, start_button_id, 23, 25, 26, 28, 27, 8, 2]
    if len(set(codes)) != len(codes) or len(set(ids)) != len(ids):
        raise ValueError('Preset logical/physical buttons must be distinct')
    if any(type(raw) is not int or not 0 <= raw < 256 for raw in ids):
        raise ValueError('Preset requires confirmed button IDs in [0,256)')
    return dict(zip(codes, ids))


class DirectFollowButtons:
    """Reuse follow arbitration locally; virtual chords never reach other controls."""
    description = '独立标签键跟随/停止、保存关系；接管键停止跟随'

    def __init__(self):
        from .follow_buttons import FollowButtons
        self.selector = FollowButtons()

    def select(self, connected, buttons, events=()):
        codes = {FOLLOW_TOGGLE: 304, FOLLOW_SAVE: 305, 311: 311}
        follow_state = {310: True, **{dst: bool(buttons.get(src)) for src, dst in codes.items()}}
        follow_events = [(codes[code], pressed, initial) for code, pressed, initial in events if code in codes]
        return self.selector.select(connected, follow_state, follow_events)


def follow_buttons_for_input(pad):
    return DirectFollowButtons() if isinstance(pad, SpacePilotInput) and DIRECT_FOLLOW_CODES <= set(pad.button_map) else None


@dataclass(frozen=True)
class InputOptions:
    kind: str = 'gamepad'
    profile: Path = DEFAULT_PROFILE
    translation_scale: float = 1.
    rotation_scale: float = 1.
    deadzone: float = 18.
    mode: str = 'all'
    dominant: bool = False
    expected_profile_sha256: str = None
    speed_profile: str = 'auto'

    def __post_init__(self):
        if self.kind not in ('gamepad', 'spacepilot'):
            raise ValueError('Unknown operator input device')
        if not all(math.isfinite(x) and x >= 0 for x in (self.translation_scale, self.rotation_scale)):
            raise ValueError('SpacePilot scales must be finite and nonnegative')
        if not math.isfinite(self.deadzone) or not 0 <= self.deadzone < 350:
            raise ValueError('SpacePilot deadzone must be in [0,350)')
        if self.mode not in ('translation', 'rotation', 'all'):
            raise ValueError('Unknown SpacePilot axis mode')
        if self.speed_profile not in ('auto', 'standalone', 'session'):
            raise ValueError('Unknown SpacePilot speed profile')


def add_input_arguments(parser):
    parser.add_argument('--input-device', choices=('gamepad', 'spacepilot'), default='gamepad',
                        help='Human input only; actor retains ownership of command topics')
    parser.add_argument('--spacepilot-map', type=Path, default=DEFAULT_PROFILE,
                        help='Confirmed libspnav IDs mapped to logical gamepad buttons')
    parser.add_argument('--spacepilot-translation-scale', '--translation-scale', type=float, default=1.5,
                        help='Human translation multiplier, bounded by the session action contract')
    parser.add_argument('--spacepilot-rotation-scale', '--rotation-scale', type=float, default=.3,
                        help='Human rotation multiplier, bounded by the session action contract')
    parser.add_argument('--spacepilot-deadzone', type=float, default=18.)
    parser.add_argument('--spacepilot-mode', choices=('translation','rotation','all'), default='all')
    parser.add_argument('--spacepilot-dominant-axis', action='store_true')
    parser.add_argument('--spacepilot-speed-profile', choices=('auto', 'standalone', 'session'), default='auto',
                        help='auto: standalone speeds for fresh unconfigured human collection; session bounds for existing runs/models')


def options_from_args(args):
    return InputOptions(kind=getattr(args, 'input_device', 'gamepad'),
                        profile=getattr(args, 'spacepilot_map', DEFAULT_PROFILE),
                        translation_scale=getattr(args, 'spacepilot_translation_scale', 1.5),
                        rotation_scale=getattr(args, 'spacepilot_rotation_scale', .3),
                        deadzone=getattr(args, 'spacepilot_deadzone', 18.),
                        mode=getattr(args, 'spacepilot_mode', 'all'),
                        dominant=getattr(args, 'spacepilot_dominant_axis', False),
                        speed_profile=getattr(args, 'spacepilot_speed_profile', 'auto'))


def collection_input_config(config, args):
    """Only a fresh unconfigured collection may establish larger action bounds."""
    options = options_from_args(args)
    if options.kind != 'spacepilot':
        return config, options
    fresh = not getattr(args, 'resume', False) and not getattr(args, 'config', None)
    profile = options.speed_profile
    if profile == 'auto':
        profile = 'standalone' if fresh else 'session'
    options = replace(options, speed_profile=profile)
    if fresh and profile == 'standalone':
        config = replace(config,
            translation_step_m=max(config.translation_step_m, .01*options.translation_scale/config.hz),
            rotation_step_rad=max(config.rotation_step_rad, math.radians(10)*options.rotation_scale/config.hz))
    # Pin resolution so preflight and transport do not silently revert to auto.
    args.spacepilot_speed_profile = profile
    SpacePilotHILMapping(config, options)  # Validate before devices/output directories.
    return config, options


class SpacePilotInput:
    """LinuxGamepad-shaped state, with six CONTINUOUS mapped SpacePilot axes.

    axes 0..5 are X/Y/Z/Rx/Ry/Rz raw values, not Linux stick/D-pad codes.
    Only SpacePilotHILMapping interprets them. Each button edge is retained.
    """
    def __init__(self, buttons, *, driver_factory=None, clock=time.monotonic):
        if driver_factory is None:
            from omi_hil_rl.hardware.spacepilot_pose import SpaceNav
            driver_factory = SpaceNav
        self.button_map = tuple(buttons)
        self.raw_to_logical = {v: k for k, v in buttons.items()}
        self.clock = clock
        self.axes, self.buttons, self.button_events = {}, {}, []
        self.connected = False
        self.error = ''
        self.blocked = set()
        self.generation = 0
        self.reset_during_poll = False
        self.last_poll = None
        self.driver = driver_factory(on_button=self._button, on_reset=self._reset)

    def _reset(self):
        self.connected = False
        self.axes.clear()
        self.buttons.clear()
        self.button_events.clear()
        self.blocked.clear()
        self.generation += 1
        self.reset_during_poll = True

    def _button(self, raw, pressed):
        code = self.raw_to_logical.get(raw)
        if code is None:
            return
        initial = not self.connected
        if initial and pressed:
            self.blocked.add(raw)
        if raw in self.blocked:
            if not pressed:
                self.blocked.remove(raw)
            self.buttons[code] = False
            self.button_events.append((code, False, True))
            return
        self.buttons[code] = bool(pressed)
        self.button_events.append((code, bool(pressed), initial))
        if code == 311 and not pressed:
            self.generation += 1

    def poll(self):
        self.button_events = []
        self.reset_during_poll = False
        try:
            now = self.clock()
            stalled = self.last_poll is not None and now-self.last_poll > .25
            self.last_poll = now
            if stalled:
                self.driver.close()  # discard buffered events, never revive old motion
                self._reset()
                self.error = 'SpacePilot polling stalled; input connection reset'
                return False
            self.driver.poll(now)
            if self.reset_during_poll or not self.driver.connected or not self.driver.name:
                self._reset()
                self.error = self.driver.message
                return False
            # SpaceNav zeroes stale input, also check the monotonic age here so
            # a slow driver call cannot return a stale nonzero movement sample.
            age = self.clock() - self.driver.last_motion
            raw = self.driver.raw if 0 <= age <= .15 else [0.] * 6
            if len(raw) != 6 or not all(math.isfinite(x) for x in raw):
                raise ValueError('Nonfinite or invalid SpacePilot motion')
            self.axes = {i: float(v) for i, v in enumerate(raw)}
            self.axes['_generation'] = self.generation
            self.connected, self.error = True, ''
            return True
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            self.driver.close()
            self._reset()
            return False

    def close(self):
        try:
            self.driver.close()
        finally:
            self._reset()


class SpacePilotHILMapping:
    def __init__(self, config, options):
        from .spacepilot_control import SpacePilotMapping
        self.speed_profile = 'session' if options.speed_profile == 'auto' else options.speed_profile
        standalone = self.speed_profile == 'standalone'
        self.mapping = SpacePilotMapping(
            rate=config.hz, speed_mm_s=10. if standalone else config.translation_step_m*config.hz*1000,
            rotation_deg_s=10. if standalone else math.degrees(config.rotation_step_rad*config.hz),
            translation_scale=options.translation_scale, rotation_scale=options.rotation_scale,
            deadzone=options.deadzone, mode=options.mode, dominant=options.dominant)
        self.limit = np.asarray(config.action_scale, dtype=float)
        peak = np.array([self.mapping.linear_speed/config.hz]*3 + [self.mapping.angular_speed/config.hz]*3)
        if standalone and np.any(peak > self.limit * (1+1e-6)):
            raise ValueError('Standalone SpacePilot speed exceeds this session/model action contract; '
                             'use a fresh collection or --spacepilot-speed-profile session. '
                             'Existing checkpoints/replay must not be rescaled in place.')
        self.generation = None

    def action(self, axes):
        generation = axes.get('_generation')
        if generation != self.generation:
            self.mapping.reset()
            self.generation = generation
        result = self.mapping.action([axes.get(i, 0.) for i in range(6)])
        # Preserve group direction while fitting the existing checkpoint/replay
        # component bounds. Scaling human input never changes the action contract.
        for section in (slice(0, 3), slice(3, 6)):
            ratio = np.max(np.abs(result[section]) / self.limit[section])
            if ratio > 1:
                result[section] /= ratio
        return result


def create_operator_input(config, gamepad='/dev/input/js0', options=None):
    from .gamepad_control import Mapping
    from .linux_gamepad import LinuxGamepad
    options = options or InputOptions()
    if options.kind == 'gamepad':
        return (LinuxGamepad(gamepad),
                Mapping(hz=config.hz, translation_m_s=config.translation_step_m*config.hz,
                        rotation_rad_s=config.rotation_step_rad*config.hz),
                dict(kind='gamepad', device=gamepad))
    buttons, info = load_button_profile(options.profile)
    if DIRECT_FOLLOW_CODES <= set(buttons) and DIRECT_FOLLOW_CODES & {
            config.start_button, config.stop_button, config.success_button,
            config.keep_button, config.discard_button}:
        raise ValueError('Direct tag-follow codes must not overlap episode/review buttons')
    if info['required_review'] is not None and config.review != info['required_review']:
        raise ValueError('This SpacePilot profile requires review=auto; manual review is disabled')
    if options.expected_profile_sha256 is not None and info['profile_sha256'] != options.expected_profile_sha256:
        raise ValueError('SpacePilot profile changed after input preflight; restart with a stable profile')
    mapping = SpacePilotHILMapping(config, options)
    info.update(translation_scale=options.translation_scale, rotation_scale=options.rotation_scale,
                deadzone=options.deadzone, mode=options.mode, dominant_axis=options.dominant,
                physical_action_limit=config.action_scale.tolist(), speed_profile=mapping.speed_profile,
                requested_translation_mm_s=mapping.mapping.linear_speed*1000,
                requested_rotation_deg_s=math.degrees(mapping.mapping.angular_speed),
                single_axis_translation_limit_mm_s=min(mapping.mapping.linear_speed, config.translation_step_m*config.hz)*1000,
                single_axis_rotation_limit_deg_s=math.degrees(min(mapping.mapping.angular_speed, config.rotation_step_rad*config.hz)))
    return SpacePilotInput(buttons), mapping, info


def required_buttons(config, home_button_code=None, *, gripper=False, tag_follow=False, input_options=None):
    required = {311, config.start_button, config.success_button, config.stop_button}
    if config.review == 'manual':
        required.update((config.keep_button, config.discard_button))
    if home_button_code is not None:
        required.add(home_button_code)
    if gripper:
        required.update((304, 305))
    if tag_follow:
        direct = False
        if input_options is not None and input_options.kind == 'spacepilot':
            buttons, _ = load_button_profile(input_options.profile)
            direct = DIRECT_FOLLOW_CODES <= set(buttons)
        required.update(DIRECT_FOLLOW_CODES if direct else (304, 305, 310))
    return required


def check_operator_input(config, args, required):
    options = options_from_args(args)
    pad, _, info = create_operator_input(config, getattr(args, 'gamepad', '/dev/input/js0'), options)
    try:
        deadline = time.monotonic() + (2.5 if options.kind == 'spacepilot' else 0.)
        while not pad.poll():
            if time.monotonic() >= deadline:
                raise ValueError(options.kind+' unavailable: '+pad.error)
            time.sleep(.01)
        if not set(required) <= set(pad.button_map):
            raise ValueError('Configured operator buttons missing: '+str(sorted(set(required)-set(pad.button_map))))
    finally:
        pad.close()
    print('人工输入：'+json.dumps(info, ensure_ascii=False), flush=True)
    if options.kind == 'spacepilot':
        print(f"SpacePilot速度方案={info['speed_profile']}；单轴指令上限 "
              f"{info['single_axis_translation_limit_mm_s']:.3f} mm/s、"
              f"{info['single_axis_rotation_limit_deg_s']:.3f} degree/s。", flush=True)
    return (replace(options, expected_profile_sha256=info['profile_sha256'])
            if options.kind == 'spacepilot' else options)
