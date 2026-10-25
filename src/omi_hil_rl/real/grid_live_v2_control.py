"""Read-only EEF and wire-command display. No robot/command publishers."""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .grid_live_v2_core import NS, font, number

CHANNELS = ('human', 'policy')


def six(values):
    result = np.asarray(values, dtype=float)
    if result.shape != (6,) or not np.isfinite(result).all():
        raise ValueError('Expected six finite command components')
    return result.tolist()


def pose_values(message):
    p, q = message.pose.position, message.pose.orientation
    xyz = np.array([p.x, p.y, p.z], dtype=float)
    quat = np.array([q.x, q.y, q.z, q.w], dtype=float)
    norm = float(np.linalg.norm(quat))
    if not np.isfinite(xyz).all() or not np.isfinite(quat).all() or abs(norm-1) > .01:
        raise ValueError('Invalid EEF position/quaternion')
    x, y, z, w = quat/norm
    roll = math.atan2(2*(w*x+y*z), 1-2*(x*x+y*y))
    pitch = math.asin(float(np.clip(2*(w*y-z*x), -1, 1)))
    yaw = math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))
    return dict(xyz_mm=(xyz*1000).tolist(), rpy_deg=np.rad2deg([roll, pitch, yaw]).tolist(),
                quaternion_xyzw=quat.tolist(), frame=message.header.frame_id,
                header_ns=message.header.stamp.sec*10**9+message.header.stamp.nanosec)


class Signals:
    def __init__(self):
        self.values = {}
        self.routes = {}
        self.command_frame = 'unknown'
        self.arm = 'unknown'
        self.discovery = 'waiting for receiver parameters'

    def route(self, source, topic):
        if topic != self.routes.get(source):
            self.routes[source] = topic
            self.values.pop(source, None)

    def ingest(self, key, message, now):
        try:
            if key == 'eef':
                value = pose_values(message)
            elif key in CHANNELS:
                dims = message.layout.dim
                ident = dims[0].label if dims and dims[0].label.startswith('hil:') else None
                value = dict(components=six(message.data), command_id=ident)
            elif key == 'receipt':
                raw = json.loads(message.data, parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
                if (not isinstance(raw, dict) or type(raw.get('accepted')) is not bool
                        or not isinstance(raw.get('status'), str)):
                    raise ValueError('Invalid command receipt')
                value = {k: raw.get(k) for k in ('command_id', 'action_source', 'accepted', 'status', 'finished', 'execution_confirmed')}
            else:
                raise ValueError('Unknown signal')
            self.values[key] = dict(value=value, received_ns=now, error=None)
        except (ValueError, TypeError, AttributeError, IndexError, KeyError, OverflowError) as exc:
            self.values[key] = dict(value=None, received_ns=now, error=str(exc)[:240])

    def snapshot(self, now):
        signals = {}
        for key in ('eef', 'human', 'policy', 'receipt'):
            item = self.values.get(key)
            age = None if item is None else max(0, now-item['received_ns'])/1e6
            state = ('WAITING' if item is None else 'BAD_DATA' if item['error'] else
                     'STALE' if age > (250 if key in CHANNELS else 500) else 'LIVE')
            signals[key] = dict(state=state, age_ms=age, value=None if item is None else item['value'],
                                error=None if item is None else item['error'])
        return dict(signals=signals, routes=dict(self.routes), command_frame=self.command_frame,
                    arm=self.arm, discovery=self.discovery)


def command_geometry(values, translation_range, rotation_range):
    """Display clipping only; numerical values always remain the received values."""
    values = np.asarray(six(values))
    limits = np.array([translation_range]*3+[rotation_range]*3)
    if not np.isfinite(limits).all() or np.any(limits <= 0):
        raise ValueError('Invalid display range')
    return np.clip(values/limits, -1, 1).tolist(), (np.abs(values)>limits).tolist()


def control_image(snapshot, translation_range=1.5, rotation_range=1.):
    image = Image.new('RGB', (1800, 620), '#151c26')
    draw = ImageDraw.Draw(image)
    f, large = font(22), font(28)
    signals = snapshot.get('signals', {})
    for col, source in enumerate(('eef', *CHANNELS)):
        x = 20+col*600
        item = signals.get(source, {})
        state = item.get('state', 'WAITING')
        value = item.get('value')
        color = dict(eef='#8aefae', human='#64c7ff', policy='#bb9cff')[source] if state == 'LIVE' else '#818b99'
        is_pose = source == 'eef'
        title = 'END EFFECTOR' if is_pose else source.upper()
        draw.text((x, 12), title, font=large, fill=color)
        draw.text((x, 53), f'{state} | RX age {number(item.get("age_ms"))} ms', font=f,
                  fill=color if state == 'LIVE' else '#ffb36b')
        description = 'FEEDBACK POSE | mm / RPY deg' if is_pose else 'COMMAND DELTA | mm / SDK ABC deg'
        draw.text((x, 89), description, font=font(20), fill='white')
        frame = (value.get('frame', 'unknown') if value else 'unknown') if is_pose else snapshot.get('command_frame', 'unknown')
        draw.text((x, 121), 'Frame: '+str(frame)[:35], font=font(20), fill='#a9c6e5')
        topic = '/tj/info/eef_left' if is_pose else snapshot.get('routes', {}).get(source, 'waiting for receiver route')
        draw.text((x, 152), topic[:48], font=font(18), fill='#a9c6e5')
        if is_pose:
            values = value['xyz_mm']+value['rpy_deg'] if value else None
            labels = ('X mm', 'Y mm', 'Z mm', 'R deg', 'P deg', 'Y deg')
            limits = (1500., 180.)
        else:
            values = value['components'] if value else None
            labels = ('dX mm', 'dY mm', 'dZ mm', 'dA deg', 'dB deg', 'dC deg')
            limits = (translation_range, rotation_range)
        fractions, overflow = command_geometry(values, *limits) if values is not None else ([0]*6, [False]*6)
        for axis, label in enumerate(labels):
            y = 198+axis*45
            center, radius = x+235, 125
            draw.text((x, y), label, font=f, fill='white')
            draw.rectangle((center-radius, y+3, center+radius, y+23), fill='#303b4d')
            draw.line((center, y, center, y+26), fill='#ccd6e5', width=2)
            if values is not None:
                end = center+int(radius*fractions[axis])
                if end != center:
                    draw.rectangle((min(center, end), y+4, max(center, end), y+22),
                                   fill='#ff776c' if overflow[axis] and state == 'LIVE' else color)
                precision = (3 if axis < 3 else 2) if is_pose else 4
                text = f'{values[axis]:+.{precision}f}'
            else:
                text = '--'
            draw.text((x+380, y), text, font=f, fill=color if values is not None else '#ffb36b')
        draw.text((x, 470), f'Scale: +/-{limits[0]:g} mm, +/-{limits[1]:g} deg', font=font(18), fill='#a9c6e5')
        note = 'R/P/Y = roll/pitch/yaw; absolute pose' if is_pose else f'Received delta; receiver arm={snapshot.get("arm", "unknown")}'
        draw.text((x, 498), note, font=font(18), fill='#a9c6e5')
        if col:
            draw.line((x-12, 12, x-12, 518), fill='#303b4d', width=2)
    receipt = signals.get('receipt', {})
    v = receipt.get('value')
    text = ('No receipt received' if not v else
            f'{v.get("action_source") or "unknown"} | {v["status"]} | accepted={v["accepted"]} | {(v.get("command_id") or "untagged")[:40]}')
    draw.text((20, 530), f'Last receipt [{receipt.get("state", "WAITING")}]: '+text, font=font(20), fill='#ffd080')
    draw.text((20, 565), 'EEF = feedback pose; HUMAN / POLICY = received commands, not ownership. Grey = stale; red = beyond display scale.', font=font(19), fill='#a9c6e5')
    draw.text((20, 594), str(snapshot.get('discovery', ''))[:140], font=font(17), fill='#a9c6e5')
    return image


def run_control(args):
    import rclpy
    from rcl_interfaces.srv import GetParameters
    from geometry_msgs.msg import PoseStamped
    from std_msgs.msg import Float64MultiArray, String, Header
    from sensor_msgs.msg import Image as ImageMsg
    from rclpy.executors import SingleThreadedExecutor, ExternalShutdownException
    from .grid_live_v2 import ros_node, close_node, latest_qos, write_json
    from .tactile_live import image_message

    node = ros_node('omi_live_v2_control_bar')
    state = Signals()
    lock = threading.Lock()
    subscriptions = {}
    pending = dict(future=None, since=0.)
    overrides = dict(human=args.manual_topic, policy=args.policy_topic)
    client = node.create_client(GetParameters, args.receiver_node.rstrip('/')+'/get_parameters')
    def ingest(key, message):
        with lock:
            state.ingest(key, message, time.monotonic_ns())
    node.create_subscription(PoseStamped, '/tj/info/eef_left', lambda m: ingest('eef', m), latest_qos())
    node.create_subscription(String, '/omi/action/receipt', lambda m: ingest('receipt', m), 10)

    def set_route(source, topic):
        if not isinstance(topic, str) or not topic.startswith('/') or any(c.isspace() for c in topic):
            raise ValueError('Invalid command topic')
        if state.routes.get(source) == topic:
            return
        if source in subscriptions:
            node.destroy_subscription(subscriptions[source])
        with lock:
            state.route(source, topic)
        def receive(msg):
            with lock:
                if state.routes.get(source) == topic:
                    state.ingest(source, msg, time.monotonic_ns())
        subscriptions[source] = node.create_subscription(Float64MultiArray, topic, receive, latest_qos())
    for source, topic in overrides.items():
        if topic != 'auto':
            set_route(source, topic)

    def discover():
        future = pending['future']
        if future is not None:
            if not future.done():
                if time.monotonic()-pending['since'] < 3:
                    return
                future.cancel()
                pending['future'] = None
                with lock:
                    state.discovery = 'Receiver parameter query timed out; retained routes are last-known'
                return
            pending['future'] = None
            try:
                values = future.result().values
                if len(values) != 4 or any(v.type != 4 for v in values):
                    raise ValueError('Receiver route/frame parameters unavailable')
                policy, human, frame, arm = (v.string_value for v in values)
                chosen = dict(human=human if overrides['human']=='auto' else overrides['human'],
                              policy=policy if overrides['policy']=='auto' else overrides['policy'])
                if chosen['human'] == chosen['policy']:
                    raise ValueError('Human and policy topics must be distinct')
                for source, topic in chosen.items():
                    set_route(source, topic)
                with lock:
                    state.command_frame, state.arm = frame, arm
                    state.discovery = 'Routes from receiver parameters (or explicit CLI override); read-only. Receipt is not motion completion.'
            except Exception as exc:
                with lock:
                    state.discovery = 'Route discovery: '+str(exc)[:140]
            return
        if client.service_is_ready():
            pending.update(future=client.call_async(GetParameters.Request(names=['delta_topic', 'manual_delta_topic', 'delta_frame', 'arm'])), since=time.monotonic())
        else:
            with lock:
                state.discovery = 'Receiver parameter service unavailable; auto routes wait. EEF display remains independent.'
    node.create_timer(1., discover)
    publisher = node.create_publisher(ImageMsg, NS+'/control_bar', latest_qos())
    telemetry = node.create_publisher(String, NS+'/control/status', 1)
    executor = SingleThreadedExecutor();executor.add_node(node)
    errors = []
    def spin():
        try:
            executor.spin()
        except ExternalShutdownException:
            pass
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=spin, daemon=True, name='control-bar-receiver');thread.start()
    last_write = 0.
    try:
        while rclpy.ok() and not errors:
            start = time.monotonic()
            with lock:
                snapshot = state.snapshot(time.monotonic_ns())
            image = control_image(snapshot, args.command_translation_range_mm, args.command_rotation_range_deg)
            draw_end = time.monotonic()
            header = Header();header.stamp = node.get_clock().now().to_msg();header.frame_id = 'read_only_control_status'
            publisher.publish(image_message(np.asarray(image), header, 'rgb8'))
            snapshot.update(schema='omi-control-bar-v1', state='OK', emitted_mono_ns=time.monotonic_ns(),
                            render_ms=(draw_end-start)*1000, publish_ms=(time.monotonic()-draw_end)*1000)
            telemetry.publish(String(data=json.dumps(snapshot, allow_nan=False)))
            if start-last_write > .5:
                try:
                    write_json(Path(args.output)/'control_status.json', snapshot)
                except OSError as exc:
                    node.get_logger().error(f'Control diagnostic save failed: {exc}')
                last_write = start
            time.sleep(max(.001, .1-(time.monotonic()-start)))
        if errors:
            raise errors[0]
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown(timeout_sec=2.);thread.join(timeout=2.);close_node(node)
