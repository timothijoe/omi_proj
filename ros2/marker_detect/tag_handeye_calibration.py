#!/usr/bin/env python3
"""Read-only tag10 multi-pose hand-eye calibration. S/LB+B capture, C/LB+A solve."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from omi_hil_rl.real.tag_handeye import (PoseHistory, StableCapture, pose_message, append_sample,
                                        solve, atomic_json, MIN_SAMPLES)
from omi_hil_rl.real.tag_follow_camera import ROSCamera
from omi_hil_rl.real.tag_follow import FollowButtons


def save_result(output, samples, context, samples_path):
    result = solve(samples)
    result.update(context, samples_file=str(samples_path.resolve()))
    if output.exists() and output.stat().st_size:
        backup = output.with_name(output.stem + '.backup_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
        backup.write_bytes(output.read_bytes())
        print(f'旧标定备份: {backup}', flush=True)
    atomic_json(output, result)
    print(f'标定通过并保存: {output}\n'
          f'训练样本平均残差: {result["residual_trans_mm_mean"]:.2f} mm / '
          f'{result["residual_rot_deg_mean"]:.2f} deg\n'
          f'留出验证 RMS: {result["validation_trans_mm_rms"]:.2f} mm / '
          f'{result["validation_rot_deg_rms"]:.2f} deg', flush=True)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT / 'ros2/marker_detect/handeye_result.json')
    p.add_argument('--image-topic', default='/camera/camera/color/image_raw')
    p.add_argument('--camera-info-topic', default='/camera/camera/color/camera_info')
    p.add_argument('--eef-topic', default='/tj/info/eef_left')
    p.add_argument('--device', default='/dev/input/js0')
    p.add_argument('--no-gamepad', action='store_true')
    p.add_argument('--solve-samples', type=Path, help='Offline solve from a saved sampling session')
    args = p.parse_args(argv)
    if args.solve_samples:
        data = json.loads(args.solve_samples.read_text())
        if data.get('schema') != 'omi-tag10-handeye-samples-v1':
            p.error('Unsupported sample file')
        save_result(args.output, data['samples'], data['context'], args.solve_samples)
        return

    import rclpy
    from rclpy.signals import SignalHandlerOptions
    from rclpy.qos import qos_profile_sensor_data
    from geometry_msgs.msg import PoseStamped
    from tag_pose import TagPoseEstimator
    from omi_hil_rl.real.linux_gamepad import LinuxGamepad

    samples = []
    samples_path = args.output.with_name('handeye_samples_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')
    context = dict(eef_topic=args.eef_topic, base_frame='base_link',
                   image_topic=args.image_topic, camera_info_topic=args.camera_info_topic,
                   tcp_source='receiver calibrated TCP FK; keep receiver TCP settings unchanged')
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node('tag10_handeye_calibration')
    history = PoseHistory()
    feedback_error = 'Waiting for TCP feedback'
    pad = None if args.no_gamepad else LinuxGamepad(args.device)
    buttons = FollowButtons()
    capture = None
    capture_deadline = 0.
    estimator = signature = fixed_signature = None
    last_sequence, last_stamp = -1, float('-inf')
    last_print = 0.
    view = None
    status = 'Move to a pose, hold still, then press S'
    result = None
    win = 'Tag10 hand-eye calibration - READ ONLY'

    def on_pose(msg):
        nonlocal feedback_error
        try:
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
            now = node.get_clock().now().nanoseconds / 1e9
            if not 0 <= now - stamp < .5:
                raise ValueError('TCP timestamp stale/future')
            history.add(stamp, pose_message(msg))
            feedback_error = ''
        except ValueError as exc:
            history.values.clear()
            feedback_error = str(exc)

    def persist():
        atomic_json(samples_path, dict(schema='omi-tag10-handeye-samples-v1', context=context,
                                      tag_id=10, tag_size_m=.051, samples=samples))

    def perform(action):
        nonlocal capture, capture_deadline, status, result
        if action == 'capture':
            if capture is not None:
                return
            capture = StableCapture(node.get_clock().now().nanoseconds / 1e9)
            result = None
            capture_deadline = time.monotonic() + 8.
            status = 'Capturing: HOLD STILL (about 1-2 seconds)'
            print('采样请求：请停稳约 2 秒，等待“样本已保存”。', flush=True)
        elif action == 'solve':
            capture = None
            try:
                result = save_result(args.output, samples, context, samples_path)
                status = 'CALIBRATION SAVED - Q to exit; restart following to load'
            except (ValueError, OSError) as exc:
                status = str(exc)
                print(f'暂未生成标定: {exc}', flush=True)
        elif action == 'delete':
            capture = None
            result = None
            if samples:
                samples.pop()
                persist()
            status = f'Deleted last sample; {len(samples)} remain'
        elif action == 'cancel':
            capture = None
            status = 'Capture cancelled'

    print('只读标定：不发布机械臂运动指令。固定相机与末端 tag10（黑框外沿 51mm）。\n'
          '你通过原有手动方式移动机械臂；每次停稳后按 S/空格 或 LB+305 采样。\n'
          '采集 15-25 个姿态，包含不同位置以及绕不同轴的俯仰/偏航/滚转。\n'
          'C 或 LB+304 求解；D 删除上一条；RB 取消本次采样；Q/ESC 退出。\n'
          f'有效结果输出: {args.output}\n原始样本自动保存: {samples_path}', flush=True)
    try:
        camera = ROSCamera(node, args.image_topic, args.camera_info_topic)
        node.create_subscription(PoseStamped, args.eef_topic, on_pose, qos_profile_sensor_data)
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=.002)
            # Drain ready callbacks before detection so high-rate TCP feedback
            # does not accumulate behind image processing in this read-only UI.
            for _ in range(6):
                rclpy.spin_once(node, timeout_sec=0.)
            now = node.get_clock().now().nanoseconds / 1e9
            state = feedback_error
            frame = camera.preview
            if frame is not None and frame[0] != last_sequence:
                last_sequence, image, stamp, received, k, d, frame_id = frame
                new_signature = (image.shape, k.tobytes(), d.tobytes(), frame_id)
                if fixed_signature is not None and new_signature != fixed_signature:
                    raise RuntimeError('Camera intrinsics/frame changed: restart calibration with a new session')
                if stamp <= last_stamp:
                    capture = None
                    history.values.clear()
                    status = 'Image timestamp repeated/backwards; capture again'
                    estimator = None
                last_stamp = stamp
                if estimator is None or new_signature != signature:
                    estimator = TagPoseEstimator(k, d, {10: .051}, family='tag36h11',
                                                 image_width=image.shape[1], nthreads=2, depth_mode='off')
                    signature = new_signature
                observations = estimator.process(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), stamp)
                tag = observations.get(10)
                view = image.copy()
                age = now - stamp
                state = f'Image age {age*1000:.0f}ms; TCP history {len(history.values)}'
                valid_tag = (tag is not None and not tag.rejected and tag.side_px >= 30
                             and np.isfinite(tag.reproj_rms) and tag.reproj_rms <= 2.)
                if tag is not None:
                    color = (0, 255, 0) if valid_tag else (0, 0, 255)
                    cv2.polylines(view, [tag.corners.astype(int)], True, color, 2)
                    cv2.drawFrameAxes(view, k, d, cv2.Rodrigues(tag.T_raw[:3, :3])[0], tag.T_raw[:3, 3], .04)
                    state += f'; tag10 {tag.side_px:.0f}px reproj {tag.reproj_rms:.2f}px'
                else:
                    state += '; tag10 NOT FOUND'
                if capture is not None and stamp >= capture.after:
                    try:
                        if not valid_tag:
                            raise ValueError('Tag10 missing/rejected/small or reprojection >2px')
                        if feedback_error or not history.values or not 0 <= now - history.values[-1][0] < .3:
                            raise ValueError(feedback_error or 'TCP feedback missing/stale')
                        robot_stamp, a = history.match(stamp)
                        sample = capture.add(stamp, robot_stamp, a, tag.T_raw, history.values[-1][1], now)
                        if sample is not None:
                            append_sample(samples, sample)
                            fixed_signature = new_signature
                            context.update(camera_frame=frame_id, image_size=[image.shape[1], image.shape[0]],
                                           camera_matrix=k.tolist(), distortion=d.tolist())
                            persist()
                            capture = None
                            status = f'Saved {len(samples)} samples. MOVE / ROTATE before next S.'
                            print(f'样本 {len(samples)} 已保存（{sample["frames"]} 帧，'
                                  f'最大配对时间差 {sample["max_pair_skew_ms"]:.1f}ms）。'
                                  '请改变位置/朝向后再采样。', flush=True)
                    except ValueError as exc:
                        capture = None
                        status = str(exc)
                        print(f'采样拒绝: {exc}', flush=True)
            if capture is not None and time.monotonic() > capture_deadline:
                capture = None
                status = 'Capture timed out; check image/TCP and press S again'
                print(status, flush=True)
            if pad is not None:
                connected = pad.poll()
                action = buttons.select(connected, pad.buttons, pad.button_events)
                if action == 'save': perform('capture')
                elif action == 'toggle': perform('solve')
                elif action == 'stop' and capture is not None: perform('cancel')
            if time.monotonic() - last_print > 2.:
                print(f'CALIBRATION samples={len(samples)} pending={capture is not None} | {state} | {status}', flush=True)
                last_print = time.monotonic()
            display = np.zeros((480, 800, 3), np.uint8) if view is None else view.copy()
            panel = np.zeros((125, display.shape[1], 3), np.uint8)
            lines = [f'READ ONLY | samples {len(samples)} / {MIN_SAMPLES}+ | tag10 51mm',
                     'S / LB+B: capture   C / LB+A: solve   D: undo   Q: exit', state, status]
            for i, line in enumerate(lines):
                cv2.putText(panel, line[:110], (8, 24 + i*28), cv2.FONT_HERSHEY_SIMPLEX,
                            .46, (0, 230, 0) if result else (0, 220, 255), 1, cv2.LINE_AA)
            cv2.imshow(win, np.vstack((panel, display)))
            key = cv2.waitKey(1) & 0xff
            if key in (ord('q'), 27): break
            if key in (ord('s'), ord(' ')): perform('capture')
            elif key == ord('c'): perform('solve')
            elif key == ord('d'): perform('delete')
    except KeyboardInterrupt:
        pass
    finally:
        if pad is not None: pad.close()
        cv2.destroyAllWindows()
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()
        print(f'标定采样已退出：{len(samples)} 个样本；原始记录 {samples_path}', flush=True)


if __name__ == '__main__':
    main()
