#!/usr/bin/env python3
"""Bind real SpacePilot buttons to HIL roles, or preview them; no ROS/robot output."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from omi_hil_rl.hardware.spacepilot_pose import SpaceNav
from omi_hil_rl.hil.config import HILConfig, load_config
from omi_hil_rl.real.operator_input import (
    DEFAULT_PROFILE, PROFILE_SCHEMA, PROFILE_FRAME, InputOptions, button_labels,
    load_button_profile, create_operator_input, oct17_buttons, DIRECT_FOLLOW_CODES,
    follow_buttons_for_input,
)


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=DEFAULT_PROFILE)
    p.add_argument('--config', type=Path, help='Existing run config.json for nondefault logical codes')
    p.add_argument('--home-button-code', type=int, default=314)
    p.add_argument('--preset', choices=('oct17',), help='User layout: Menu takeover, key1 start, dedicated tag buttons')
    p.add_argument('--start-button-id', type=int, help='Already measured key1 ID for --preset oct17; otherwise capture it')
    p.add_argument('--direct-follow', action='store_true', help='Bind two independent tag actions instead of LB chords')
    p.add_argument('--translation-scale', type=float, default=1.5, help='Read-only preview human translation scale')
    p.add_argument('--rotation-scale', type=float, default=.3, help='Read-only preview human rotation scale')
    p.add_argument('--assign', action='append', default=[], metavar='LOGICAL=DEVICE',
                   help='Create a complete profile from already confirmed IDs, without device connection')
    modes = p.add_mutually_exclusive_group()
    modes.add_argument('--show', action='store_true')
    modes.add_argument('--preview', action='store_true')
    return p


def preview(config, path, translation_scale=1.5, rotation_scale=.3):
    pad, mapping, info = create_operator_input(config, options=InputOptions(kind='spacepilot', profile=path,
        translation_scale=translation_scale, rotation_scale=rotation_scale))
    follow = follow_buttons_for_input(pad)
    print('只读预览，不连接ROS；逻辑311=接管，315=开始，308=成功，307=结束（自定义配置以列表为准）。')
    print(json.dumps(info, ensure_ascii=False, indent=2))
    last = None
    next_log = 0.
    try:
        while True:
            connected = pad.poll()
            if follow is not None:
                tag_action = follow.select(connected, pad.buttons, pad.button_events)
                if tag_action in ('toggle', 'save'):
                    print('标签操作预览：'+('开启/停止跟随' if tag_action == 'toggle' else '保存关系')+'（未执行）', flush=True)
            pressed = sorted(k for k, v in pad.buttons.items() if v)
            action = mapping.action(pad.axes) if connected and pad.buttons.get(311) else config.physical_action([0]*6)
            state = (connected, tuple(pressed), tuple(pad.button_events))
            now = time.monotonic()
            if state != last or now >= next_log:
                print(f'连接={connected} 逻辑按钮={pressed} 事件={pad.button_events} '
                      f'归一化人工动作={config.normalized_action(action).round(3).tolist()} '
                      f'错误={pad.error}', flush=True)
                next_log, last = now+.5, state
            time.sleep(.01)
    finally:
        pad.close()


def capture(labels):
    events, held, result = [], set(), {}
    reset = [False]
    def on_button(number, pressed):
        events.append((number, pressed))
        if pressed:
            held.add(number)
        else:
            held.discard(number)
    def on_reset():
        reset[0] = True
        events.clear()
        held.clear()
    driver = SpaceNav(on_button=on_button, on_reset=on_reset)
    try:
        deadline = time.monotonic()+3
        while not (driver.connected and driver.name):
            if time.monotonic() > deadline:
                raise ValueError('SpacePilot不可用：'+driver.message)
            driver.poll(time.monotonic())
            time.sleep(.01)
        reset[0] = False
        device = driver.name
        for code, label in labels.items():
            # Consume previous events before offering the next role; release is
            # mandatory so a held key never binds two roles.
            driver.poll(time.monotonic())
            events.clear()
            candidate = None
            print(f'\n逻辑键 {code}：{label}\n请选择一个实体键，按下并松开。', flush=True)
            while True:
                driver.poll(time.monotonic())
                if reset[0] or not driver.connected or not driver.name:
                    raise ValueError('输入连接变化，配置未保存；请重试')
                batch, events[:] = events[:], []
                if len({number for number, pressed in batch if pressed}) > 1:
                    candidate = None
                    print('一次只按一个按键；请全部松开后重试。', flush=True)
                    continue
                accepted = None
                for number, pressed in batch:
                    if pressed:
                        if number in result.values():
                            print(f'ID {number} 已用于其他功能，请换一个按键。', flush=True)
                            candidate = None
                        elif len(held) <= 1:
                            candidate = number
                        else:
                            candidate = None
                    elif number == candidate:
                        accepted = number
                if accepted is not None and not held:
                    result[code] = accepted
                    print(f'已绑定：逻辑 {code} ← 设备 ID {accepted}', flush=True)
                    break
                time.sleep(.01)
        return result, device
    finally:
        driver.close()


def main():
    p = build_parser()
    args = p.parse_args()
    config = load_config(args.config) if args.config else HILConfig(review='auto')
    if args.start_button_id is not None and not args.preset:
        p.error('--start-button-id requires --preset oct17')
    if args.preset and args.assign:
        p.error('--preset and --assign cannot be combined')
    if args.home_button_code in {config.start_button,config.success_button,config.stop_button,
                                  config.keep_button,config.discard_button,311,310} or args.home_button_code < 0:
        p.error('home button must not collide with episode/enable/modifier buttons')
    labels = button_labels(config, args.home_button_code, direct_follow=args.direct_follow or bool(args.preset))
    print('请先退出其他手柄/SpacePilot/策略动作发送程序；此工具只读，但不会阻止其他进程接收设备按键。', flush=True)
    try:
        if args.show:
            buttons, info = load_button_profile(args.output)
            labels = button_labels(config, args.home_button_code, direct_follow=DIRECT_FOLLOW_CODES <= set(buttons))
            print(json.dumps(info, ensure_ascii=False, indent=2))
            for code, label in labels.items():
                print(f'{label}：逻辑{code} ← 设备ID{buttons.get(code, "未配置")}')
            return
        if args.preview:
            preview(config, args.output, args.translation_scale, args.rotation_scale)
            return
        if args.output.exists():
            p.error('输出已存在；使用 --show/--preview，或 --output 指定新的配置文件')
        if args.preset:
            if config.review != 'auto':
                raise ValueError('该预设关闭人工审阅，要求review=auto')
            start_id = args.start_button_id
            device = 'SpacePilot PRO; confirmed user layout 2026-10-17'
            if start_id is None:
                captured, device = capture({config.start_button: '请只按数字1键，用作开始回合'})
                start_id = captured[config.start_button]
            buttons = oct17_buttons(config, start_id, args.home_button_code)
        elif args.assign:
            buttons = {}
            for item in args.assign:
                code, raw = item.split('=', 1)
                if int(code) in buttons:
                    raise ValueError('重复逻辑键：'+code)
                buttons[int(code)] = int(raw)
            if set(buttons) != set(labels):
                raise ValueError('需要完整键位：'+str(list(labels)))
            if any(v < 0 or v >= 256 for v in buttons.values()) or len(set(buttons.values())) != len(buttons):
                raise ValueError('实体键ID必须互不重复并在[0,256)范围内')
            device = 'user-confirmed IDs'
        else:
            buttons, device = capture(labels)
        profile = dict(schema=PROFILE_SCHEMA, axis_frame=PROFILE_FRAME, device_name=device,
                       created_utc=datetime.now(timezone.utc).isoformat(),
                       buttons={str(k): v for k,v in buttons.items()},
                       labels={str(k): v for k,v in labels.items()})
        if args.preset:
            profile.update(preset=args.preset, required_review='auto',
                physical_labels={'0':'Menu',str(start_id):'数字1','23':'ALT','25':'Ctrl',
                                 '26':'ALT左右对称键','28':'Esc左右对称键','27':'Ctrl左右对称键',
                                 '8':'第一个标签键','2':'第二个标签键'})
            profile['labels']['304'] = '夹爪闭合（自动保留，不触发审阅）'
            profile['labels']['305'] = '夹爪张开（自动保留，不触发审阅）'
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as handle:
            json.dump(profile, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        print('已保存：'+str(args.output.resolve()))
        print('用 --preview 验证所有按键与六轴，再在采集/在线入口加 --input-device spacepilot。')
    except KeyboardInterrupt:
        print('\n已退出；采集过程中退出不会保存不完整配置。')
    except (OSError, ValueError) as exc:
        p.exit(1, '错误：'+str(exc)+'\n')


if __name__ == '__main__':
    main()
