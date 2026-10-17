#!/usr/bin/env python3
"""ROS 2 AprilTag following: LB+305 saves; LB+304 toggles following.

x captures a temporary relation and follows; s/RB stops; q/ESC exits.
Images: /camera/camera/color/image_raw plus matching CameraInfo.
Commands: /omi/action/decision, 10 Hz, SDK BASE mm/ABC degrees.
"""
import argparse
from pathlib import Path
import sys
import time

import cv2
import numpy as np

# Support running this repository script without an editable package install.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from omi_hil_rl.real.tag_follow import (FollowButtons, FollowController, TAG_SIZES,
                                       load_calibration, load_default, save_default, control_description)

CMD_TOPIC = '/omi/action/decision'
CMD_RATE = 10.


from omi_hil_rl.real.tag_follow_camera import ROSCamera


def draw_observations(image, observations, k, d):
    for tid, obs in observations.items():
        color = (0, 0, 255) if obs.rejected else (0, 255, 255)
        cv2.polylines(image, [obs.corners.astype(int)], True, color, 2)
        cv2.drawFrameAxes(image, k, d, cv2.Rodrigues(obs.T[:3, :3])[0], obs.T[:3, 3], .04)
        point = tuple(obs.corners[0].astype(int))
        cv2.putText(image, f'{tid}' + (' REJECTED' if obs.rejected else ''), point,
                    cv2.FONT_HERSHEY_SIMPLEX, .7, color, 2)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image-topic', default='/camera/camera/color/image_raw')
    p.add_argument('--camera-info-topic', default='/camera/camera/color/camera_info')
    p.add_argument('--calibration', type=Path, default=Path('handeye_result.json'),
                   help='X=T_base_link_camera, Z=T_controlled_TCP_tag10; metres')
    p.add_argument('--default-pose', type=Path,
                   default=Path(__file__).resolve().parent / 'handeye_result/tag_follow_default.json')
    p.add_argument('--device', default='/dev/input/js0')
    p.add_argument('--no-gamepad', action='store_true', help='Keyboard operation only')
    p.add_argument('--headless', action='store_true')
    return p


def main(argv=None):
    args, ros_args = parser().parse_known_args(argv)
    if args.headless and args.no_gamepad:
        parser().error('--headless requires a gamepad')
    # Runtime-only imports keep geometry/buttons testable without ROS or detector.
    import rclpy
    from rclpy.signals import SignalHandlerOptions
    from std_msgs.msg import Float64MultiArray
    from omi_hil_rl.real.linux_gamepad import LinuxGamepad
    from tag_pose import TagPoseEstimator, STATIC_TAG_FILTER, MOVING_TAG_FILTER

    calibration = default = None
    try:
        calibration = load_calibration(args.calibration)
        print(f'已加载 X/Z 标定: {args.calibration}')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'标定不可用: {exc}; 可保存相对位姿，但不能启动跟随。')
    try:
        default = load_default(args.default_pose)
        print(f'已加载默认相对位姿: {args.default_pose}（未启动跟随）')
    except FileNotFoundError:
        pass
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f'默认位姿文件无效: {exc}')
    controller = FollowController(calibration, default)
    buttons = FollowButtons()
    pad = None if args.no_gamepad else LinuxGamepad(args.device)
    rclpy.init(args=ros_args, signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node('tag_follow_tag')
    publisher = node.create_publisher(Float64MultiArray, CMD_TOPIC, 1)
    estimator = signature = None
    sequence, estimator_stamp = -1, float('-inf')
    image = None
    last_cmd = last_log = 0.
    window = 'AprilTag relative pose following'

    def send(data):
        publisher.publish(Float64MultiArray(data=[float(v) for v in data]))

    def stop():
        controller.stop()
        send(np.zeros(6))

    def action(name, now):
        try:
            if name == 'stop':
                stop()
            elif name == 'save':
                stop()
                relative = controller.capture(now)
                save_default(args.default_pose, relative)
                controller.default = relative
                print(f'已保存 tag10 <- tag12 默认位姿: {args.default_pose}', flush=True)
            elif name == 'toggle':
                if controller.active:
                    stop()
                else:
                    controller.start(now)
                    print('开始按已保存的默认位姿跟随', flush=True)
            elif name == 'capture_start':
                stop()
                controller.start(now, temporary=controller.capture(now))
                print('[x] 已记录临时相对位姿并开始跟随（未覆盖磁盘默认值）', flush=True)
        except (OSError, ValueError) as exc:
            stop()
            print(f'操作未完成: {exc}', flush=True)

    print(f'图像: {args.image_topic}; 内参: {args.camera_info_topic}\n'
          f'输出: {CMD_TOPIC} @ {CMD_RATE:g}Hz, mm/ABC度; 初始停止\n'
          f'控制: {control_description()}\n'
          '时效: 从本地订阅回调接收图像起计时，120ms 超时暂停\n'
          'LB+305 保存默认位姿; LB+304 开始/停止; RB/s 停止; x 临时记录并跟随; q/ESC 退出',
          flush=True)
    try:
        camera = ROSCamera(node, args.image_topic, args.camera_info_topic)
        if not args.headless:
            cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=.005)
            # Prevent competing policy publishers from driving the same receiver.
            if node.count_publishers(CMD_TOPIC) > 1:
                raise RuntimeError(f'另一个节点正在发布 {CMD_TOPIC}，请先停止它')
            if camera.invalid_reason:
                controller.observe({}, time.monotonic())
                controller.reason = camera.invalid_reason
            frame = camera.latest
            if frame is None and not args.headless:
                frame = getattr(camera, 'preview', None)
            if frame is not None and frame[0] != sequence:
                sequence, image, stamp, received, k, d, frame_id = frame
                current_signature = (image.shape, k.tobytes(), d.tobytes(), frame_id)
                if current_signature != signature or received <= estimator_stamp:
                    estimator = TagPoseEstimator(k, d, TAG_SIZES, family='tag36h11',
                                                 image_width=image.shape[1], nthreads=8,
                                                 filter_params={10: MOVING_TAG_FILTER,
                                                                12: STATIC_TAG_FILTER},
                                                 depth_mode='off')
                    signature = current_signature
                estimator_stamp = received
                fresh = not camera.invalid_reason and 0 <= time.monotonic() - received < .12
                if fresh or not args.headless:
                    observations = estimator.process(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), received)
                    if fresh:
                        controller.observe(observations, received)
                    else:
                        controller.observe({}, time.monotonic())
                        controller.reason = camera.invalid_reason or 'camera frame stale; preview only'
                    if not args.headless:
                        image = image.copy()
                        draw_observations(image, observations, k, d)
                else:
                    controller.observe({}, time.monotonic())
                    controller.reason = 'camera frame stale'
            now = time.monotonic()
            if pad is not None:
                connected = pad.poll()
                event = buttons.select(connected, pad.buttons, pad.button_events)
                if event is not None:
                    # Disconnected idle pads need no additional unthrottled zero.
                    if event != 'stop' or controller.active:
                        action(event, now)
            if now - last_cmd >= 1. / CMD_RATE:
                last_cmd = now
                command = controller.command(now)
                send(command)
                if now - last_log >= 1.:
                    receive_age_ms = None if camera.latest is None else round((now - camera.latest[3]) * 1000, 1)
                    state = controller.state(now)
                    print(f'{state} | error xyz/RxRyRz(mm/rotvec-deg)='
                          f'{np.round(controller.error_mm_rotvec_deg, 3).tolist()} | '
                          f'command(mm/ABC-deg)={np.round(command, 3).tolist()} | '
                          f'receive_age_ms={receive_age_ms} | '
                          f'{controller.reason}' + (f' | gamepad: {pad.error}' if pad and pad.error else ''),
                          flush=True)
                    last_log = now
            if not args.headless:
                display = np.zeros((160, 900, 3), np.uint8) if image is None else image.copy()
                state = controller.state(now)
                cv2.putText(display, state + ' | LB+B save / LB+A follow / RB stop', (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 255, 0), 2)
                cv2.putText(display, controller.reason, (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 180, 255), 2)
                if display.shape[1] > 1280:
                    display = cv2.resize(display, None, fx=.5, fy=.5)
                cv2.imshow(window, display)
                key = cv2.waitKey(1) & 0xff
                if key in (ord('q'), 27):
                    break
                if key == ord('s'):
                    action('stop', time.monotonic())
                elif key == ord('x'):
                    action('capture_start', time.monotonic())
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if rclpy.ok():
                stop()
        finally:
            if pad is not None:
                pad.close()
            if not args.headless:
                cv2.destroyAllWindows()
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()


if __name__ == '__main__':
    main()
