"""MJPG wrist acquisition: bounded recording FIFO and latest decoded live view."""
import argparse
import json
import socket
import threading
import time

from .wrist_wire import Reassembler, message_types
from .wrist_image import TOPICS, LABELS, prepare_image
from .frame_queue import FrameQueue


def run(host, pc_host, port=50088, width=1920, height=1080, fps=30, image_mode='full',
        buffer_mode='record', buffer_frames=60, buffer_mib=64):
    import cv2
    import grpc
    import numpy as np
    import rclpy
    from sensor_msgs.msg import Image
    from std_msgs.msg import Header, String
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from .node import image_message

    types = message_types()
    channel = grpc.insecure_channel('%s:%d' % (host, port), options=(('grpc.enable_http_proxy', 0),))
    prefix = '/fish_camera.grpc_test.CameraProxy/'
    def rpc(name, request, response, streaming=False):
        method = channel.unary_stream if streaming else channel.unary_unary
        return method(prefix + name, request_serializer=types[request].SerializeToString,
                      response_deserializer=types[response].FromString)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024**2)
    udp.bind((pc_host, 0)); udp.settimeout(.2)
    stop = threading.Event(); ready = threading.Event(); lock = threading.Lock()
    state = dict(session='', error='', latest=None, received=0, overwritten=0, malformed=0)
    queue = FrameQueue(buffer_mode, buffer_frames, buffer_mib*1024**2)
    call = None; threads = []; node = None
    try:
        grpc.channel_ready_future(channel).result(timeout=5)
        request = types['StreamRequest'](codec='MJPG', width=width, height=height, fps=fps,
                   udp_port=udp.getsockname()[1], client_ip=pc_host, max_datagram=1200)
        call = rpc('OpenStream', 'StreamRequest', 'StreamEvent', True)(request)
        def events():
            try:
                for event in call:
                    if event.type == 1:
                        state['session'] = event.session_id
                        state['negotiated'] = [event.width, event.height, event.fps, event.codec]
                        ready.set()
                    elif event.type in (3, 4):
                        state['error'] = event.message or 'server stopped stream'
                        stop.set(); ready.set()
            except grpc.RpcError as exc:
                if not stop.is_set(): state['error'] = str(exc)
            finally:
                stop.set(); ready.set()
        thread = threading.Thread(target=events, daemon=True); threads.append(thread); thread.start()
        if not ready.wait(8) or not state['session'] or stop.is_set():
            raise RuntimeError(state['error'] or 'camera OpenStream timed out')
        reassembler = Reassembler(state['session'])
        def receive():
            while not stop.is_set():
                try:
                    packet, peer = udp.recvfrom(65535)
                    if peer[0] != host: continue
                    with lock:
                        frame = reassembler.push(packet)
                        if frame is not None:
                            queue.put((*frame, time.time_ns(), time.monotonic()))
                            state['received'] += 1
                except socket.timeout:
                    with lock:
                        reassembler.expire()
                    continue
                except ValueError:
                    state['malformed'] += 1
                except OSError:
                    break
        thread = threading.Thread(target=receive, daemon=True); threads.append(thread); thread.start()
        rclpy.init(args=[]); node = rclpy.create_node('omi_wrist_camera')
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        publisher = node.create_publisher(Image, TOPICS[image_mode], qos)
        record_pub = node.create_publisher(Image, TOPICS[image_mode]+'/record',
            QoSProfile(depth=32, reliability=ReliabilityPolicy.RELIABLE)) if buffer_mode == 'record' else None
        metadata_pub = node.create_publisher(String, '/omi/wrist/metadata', 64)
        status_pub = node.create_publisher(String, '/omi/wrist/status', 2)
        last_good = time.monotonic(); last_status = 0.; published = 0; latest_stats = {}
        state.update(record_published=0, decode_failures=0, decoded=0, live_overwrites=0,
                     last_good=last_good, latest_stats={})
        node.get_logger().info('MJPG session started: ' + str(state.get('negotiated')) + ' | ' + LABELS[image_mode])
        def decode():
            while not stop.is_set():
                frame = queue.pop()
                if frame is None:
                    stop.wait(.001)
                    continue
                fid, server_time, jpeg, receive_ns, received_at = frame
                begin = time.monotonic()
                try:
                    value = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if value is None:
                        raise ValueError('JPEG decode failed')
                    value, image_metadata = prepare_image(value, image_mode)
                    header = Header(); header.frame_id = 'omi_wrist_camera_optical'
                    header.stamp.sec, header.stamp.nanosec = divmod(receive_ns, 10**9)
                    msg = image_message(value, header)
                except Exception as exc:
                    with lock:
                        state['decode_failures'] += 1
                        state['last_decode_error'] = dict(frame_id=fid, error=f'{type(exc).__name__}: {exc}'[:240])
                    continue
                try:
                    if record_pub is not None:
                        record_pub.publish(msg)
                    done = time.monotonic()
                    audit = dict(schema_version=4, field='wrist_rgb', sdk_frame_id=fid,
                        header_ns=receive_ns, source_timestamp_ns=None,
                        host_receive_ns=receive_ns, host_publish_ns=time.time_ns(),
                        queue_wait_ms=(begin-received_at)*1000,
                        frame_id=fid, decode_and_publish_ms=(done-begin)*1000,
                        receive_to_publish_ms=(done-received_at)*1000,
                        server_timestamp_unverified=server_time,
                        timestamp_kind='host_complete_jpeg_receive_not_exposure', **image_metadata)
                    metadata_pub.publish(String(data=json.dumps(audit)))
                    with lock:
                        state['decoded'] += 1
                        state['record_published'] += int(record_pub is not None)
                        state['live_overwrites'] += int(state['latest'] is not None)
                        state['latest'] = msg
                        state['latest_stats'] = audit
                        state['last_good'] = done
                except Exception as exc:
                    with lock:
                        state['error'] = 'publisher: '+str(exc)
                    stop.set()
        thread = threading.Thread(target=decode, daemon=True); threads.append(thread); thread.start()
        while rclpy.ok() and not stop.is_set():
            with lock:
                msg = state['latest']; state['latest'] = None
                last_good = state['last_good']; latest_stats = dict(state['latest_stats'])
            if msg is not None:
                publisher.publish(msg)
                published += 1
            now = time.monotonic()
            if now-last_status >= 1:
                with lock:
                    reassembly_stats = dict(reassembler.counters)
                status_pub.publish(String(data=json.dumps(dict(state='streaming' if now-last_good < .5 and published else 'stale',
                    published=published, received=state['received'], overwritten=queue.stats().get('latest_overwrites', 0),
                    malformed=state['malformed'], seconds_since_frame=now-last_good,
                    record_published=state['record_published'], decode_failures=state['decode_failures'],
                    last_decode_error=state.get('last_decode_error'),
                    live_overwrites=state['live_overwrites'], queue=queue.stats(),
                    reassembly=reassembly_stats,
                    negotiated=state.get('negotiated'), **latest_stats))))
                last_status = now
            if now-last_good > 8: raise RuntimeError('No valid wrist image for 8 seconds')
            rclpy.spin_once(node, timeout_sec=.001)
        if state['error']: raise RuntimeError(state['error'])
    finally:
        stop.set()
        if state['session']:
            try: rpc('StopStream', 'StopStreamRequest', 'StopStreamResponse')(
                types['StopStreamRequest'](session_id=state['session']), timeout=2)
            except Exception: pass
        if call is not None: call.cancel()
        udp.close(); channel.close()
        for thread in threads: thread.join(timeout=1)
        if node is not None:
            node.get_logger().info('Camera shutdown accounting: '+json.dumps(dict(
                queue=queue.stats(), record_published=state.get('record_published', 0),
                decode_failures=state.get('decode_failures', 0),
                pending_frames_abandoned=queue.stats()['pending_frames'],
                worker_threads_still_exiting=sum(thread.is_alive() for thread in threads))))
            node.destroy_node()
            if rclpy.ok(): rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True); parser.add_argument('--pc-host', required=True)
    parser.add_argument('--port', type=int, default=50088)
    parser.add_argument('--width', type=int, default=1920); parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--image-mode', choices=['full', 'roi'], default='full')
    parser.add_argument('--buffer-mode', choices=['latest', 'record'], default='record')
    parser.add_argument('--buffer-frames', type=int, default=60)
    parser.add_argument('--buffer-mib', type=int, default=64)
    args = parser.parse_args()
    if min(args.width, args.height, args.fps, args.buffer_frames, args.buffer_mib) <= 0:
        parser.error('dimensions/fps/buffer limits must be positive')
    try: run(**vars(args))
    except KeyboardInterrupt: pass


if __name__ == '__main__': main()
