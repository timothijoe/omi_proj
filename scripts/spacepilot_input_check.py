#!/usr/bin/env python3
"""Record SpacePilot input/neutral timing locally; never initialize ROS or publish."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from omi_hil_rl.hardware.spacepilot_pose import SpaceNav
from omi_hil_rl.real.spacepilot_control import DEFAULT_ENABLE_BUTTON, EnableGate, SpacePilotMapping, selected_action
from omi_hil_rl.real.sdk_action import output_action


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=30.)
    parser.add_argument('--enable-button', type=int, default=DEFAULT_ENABLE_BUTTON)
    parser.add_argument('--translation-scale', type=float, default=1.5)
    parser.add_argument('--rotation-scale', type=float, default=.3)
    parser.add_argument('--deadzone', type=float, default=18.)
    args = parser.parse_args()
    try:
        if not math.isfinite(args.seconds) or not 0 < args.seconds <= 300:
            raise ValueError('seconds must be in (0, 300]')
        mapping = SpacePilotMapping(translation_scale=args.translation_scale,
                                   rotation_scale=args.rotation_scale, deadzone=args.deadzone)
        gate = EnableGate(args.enable_button)
    except ValueError as exc:
        parser.error(str(exc))

    print('只读输入采样：不连接 ROS、不发送机械臂动作。')
    print('请先退出真机发送程序；按住实体3，推动旋钮约2秒，然后松开旋钮但继续按住实体3约3秒，最后松开实体3。')
    print('可以重复两轮。不要为了采样重新启动机器人控制；旋钮与按钮原始事件会自动保存。')
    try:
        input(f'准备好后按回车开始 {args.seconds:g} 秒采样，Ctrl+C 可提前保存：')
    except (EOFError, KeyboardInterrupt):
        return

    rows, buttons, edges = [], [], []
    start = time.monotonic()

    def button(number, pressed):
        gate.on_button(number, pressed)
        buttons.append(dict(t_s=time.monotonic()-start, button=number, pressed=pressed))

    driver = SpaceNav(on_button=button, on_reset=gate.reset)
    previous = previous_edge = None
    last_print = -1.
    max_poll_ms = 0.
    error = None
    try:
        while time.monotonic() - start < args.seconds:
            now = time.monotonic()
            before = time.perf_counter()
            driver.poll(now)
            poll_ms = (time.perf_counter()-before)*1000
            max_poll_ms = max(max_poll_ms, poll_ms)
            now = time.monotonic()
            mode, action = selected_action(driver, gate, mapping, now)
            wire = output_action(action, 'sdk-x-forward-z-left')
            row = dict(t_s=now-start, enabled=gate.enabled, mode=mode,
                       raw=driver.device_raw.copy(), mapped=driver.raw.copy(),
                       candidate=wire, motion_count=driver.events, poll_ms=poll_ms)
            key = (driver.events, driver.button_events, mode, any(wire))
            if key != previous:
                rows.append(row)
                previous = key
            edge = (gate.enabled, any(wire), mode)
            if edge != previous_edge:
                edges.append(row.copy())
                previous_edge = edge
            if now-start-last_print >= .5:
                print(f'{now-start:5.1f}s 启用={gate.enabled} 非零候选={any(wire)} '
                      f'原始六轴={driver.device_raw} 运动事件={driver.events} '
                      f'设备={driver.message}', flush=True)
                last_print = now-start
            time.sleep(.005)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    finally:
        device = driver.name
        driver.close()

    folder = ROOT / 'local/spacepilot/latency'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_input.json')
    report = dict(schema='omi-spacepilot-input-timing-v1', readonly=True,
                  clock='local monotonic receive time, not hardware acquisition time',
                  physical_release_timestamp_known=False, settings=vars(args), device=device,
                  duration_s=time.monotonic()-start, motion_events=driver.events,
                  max_poll_ms=max_poll_ms, error=error, buttons=buttons, edges=edges, rows=rows)
    with path.open('x') as handle:
        json.dump(report, handle, ensure_ascii=False)
    print(f'已保存：{path}')
    print(f'运动事件={driver.events}，按键事件={len(buttons)}，状态转换={len(edges)}。')
    print('时间表示程序收到输入的时刻；不会将它当作手松开的真实时间或机械臂端到端时延。')
    if error:
        parser.exit(1, error+'\n')


if __name__ == '__main__':
    main()
