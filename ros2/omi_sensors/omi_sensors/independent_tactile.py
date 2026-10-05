"""Independent SDK reads. No SDK access from concurrent Python threads.

Framed getters are deduplicated by their own sequence number. Unframed force
reads are explicitly NOT evidence of a new device measurement.
"""
from collections import Counter
import time

import numpy as np

from .tactile import IncompleteFrame, normalize_wrench
from .tactile_grid import block_mean

METHODS = dict(wrench='getForce', deformation='getDeformation2D', shear='getShear',
               depth='getDepth', raw='getRawImg')


class IndependentReader:
    def __init__(self, depth=True, wrench=False, raw=False):
        self.kinds = (["wrench"] if wrench else []) + ['deformation', 'shear']
        self.kinds += ['depth'] if depth else []
        self.kinds += ['raw'] if raw else []
        self.last_ids, self.previous_force = {}, None
        self.counts = {k: Counter() for k in self.kinds}
        self.errors, self.last_good_ns = {}, {}

    def read(self, sensor, kind):
        counts = self.counts[kind]
        counts['reads'] += 1
        started = time.time_ns()
        try:
            result = getattr(sensor, METHODS[kind])()
            frame = None
            if kind == 'wrench':
                framed = isinstance(result, (tuple, list)) and len(result) == 2
                if framed:
                    frame = result[0]
                    if not isinstance(frame, (int, np.integer)) or frame < 0:
                        raise IncompleteFrame('invalid force frame ID')
                array, state = normalize_wrench(result, frame)
                if array is None:
                    raise IncompleteFrame(state)
            else:
                if not isinstance(result, (tuple, list)) or len(result) != 2:
                    raise IncompleteFrame('getter has no frame ID')
                frame, value = result
                if not isinstance(frame, (int, np.integer)) or frame < 0:
                    raise IncompleteFrame('invalid frame ID')
                array = np.array(getattr(value, 'img', value), copy=True)
                if not array.size or array.dtype.kind not in 'uf' or not np.isfinite(array).all():
                    raise IncompleteFrame('empty/nonfinite field')
                if kind == 'raw':
                    if array.dtype != np.uint8 or not (array.ndim == 2 or
                            (array.ndim == 3 and array.shape[2] in (3, 4))):
                        raise IncompleteFrame('invalid raw image')
                else:
                    array = block_mean(array, channels=0 if kind == 'depth' else 2)
            ended = time.time_ns()
            if frame is not None:
                frame = int(frame)
                if self.last_ids.get(kind) == frame:
                    counts['duplicate_frame_reads'] += 1
                    self.errors.pop(kind, None)
                    return None
                if frame < self.last_ids.get(kind, -1):
                    counts['sequence_resets'] += 1
                elif kind in self.last_ids:
                    counts['source_sequence_gaps'] += max(0, frame-self.last_ids[kind]-1)
                self.last_ids[kind] = frame
            changed = None
            if kind == 'wrench':
                changed = self.previous_force is None or not np.array_equal(array, self.previous_force)
                self.previous_force = array.copy()
                counts['value_changes'] += int(changed)
                if frame is None:
                    counts['unframed_reads'] += 1
            counts['valid_reads'] += 1
            self.errors.pop(kind, None)
            self.last_good_ns[kind] = ended
            return array, dict(schema_version=4, acquisition='independent-field-v1', field=kind,
                valid=True, sdk_frame_id=frame, source_timestamp_ns=None,
                header_ns=ended, host_read_started_ns=started, host_read_finished_ns=ended,
                timestamp_kind='host_read_finished_not_exposure',
                freshness_verified=False, new_source_frame_observed=frame is not None,
                changed_since_previous_read=changed, shape=list(array.shape), dtype=str(array.dtype),
                processing_ms=(ended-started)/1e6, units='SDK units; uncalibrated',
                counters=dict(counts))
        except Exception as exc:
            counts['invalid_reads'] += 1
            self.errors[kind] = f'{type(exc).__name__}: {exc}'[:240]
            return None


def run(config, side, publish_raw=False):
    import json
    import rclpy
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from rclpy.executors import ExternalShutdownException
    from sensor_msgs.msg import Image
    from std_msgs.msg import Header, String
    from geometry_msgs.msg import WrenchStamped
    from .node import image_message
    from .tactile import connect, sdk_check, sdk_digest

    tac = config['tactile']
    digest = sdk_digest(sdk_check(tac))
    rclpy.init(args=[])
    node = rclpy.create_node('omi_tactile_'+side)
    reader = IndependentReader(tac['enable_depth'], tac['enable_wrench'], publish_raw)
    root = '/omi/tactile_grid24x16/'+side
    qos = QoSProfile(depth=32, reliability=ReliabilityPolicy.RELIABLE)
    pubs = {kind: node.create_publisher(WrenchStamped if kind == 'wrench' else Image,
            ('/omi/tactile/'+side if kind == 'raw' else root)+'/'+kind, qos) for kind in reader.kinds}
    metadata = node.create_publisher(String, root+'/metadata', qos)
    status = node.create_publisher(String, root+'/status', qos)
    sensor, retry_at, last_status = None, 0., 0.
    last_good = time.monotonic()
    error, reconnects, next_force = '', 0, 0.
    try:
        while rclpy.ok():
            tick = time.monotonic()
            if tick >= retry_at:
                try:
                    if sensor is None:
                        sensor = connect(tac, side)
                        reader.last_ids.clear()
                        last_good = tick
                    try:
                        sensor.getEvents()
                    except Exception as exc:
                        error = 'getEvents: '+str(exc)[:180]
                    # Do not gate force/other fields on getDevStatus or wait_for_new.
                    for kind in reader.kinds:
                        if kind == 'wrench':
                            if tick < next_force:
                                continue
                            next_force = tick+1/tac['fps']
                        result = reader.read(sensor, kind)
                        if result is None:
                            continue
                        array, audit = result
                        header = Header()
                        header.frame_id = 'tactile_'+side
                        header.stamp.sec, header.stamp.nanosec = divmod(audit['header_ns'], 10**9)
                        if kind == 'wrench':
                            msg = WrenchStamped(header=header)
                            msg.wrench.force.x, msg.wrench.force.y, msg.wrench.force.z = map(float, array[:3])
                            msg.wrench.torque.x, msg.wrench.torque.y, msg.wrench.torque.z = map(float, array[3:])
                        else:
                            msg = image_message(array, header)
                        try:
                            pubs[kind].publish(msg)
                            reader.counts[kind]['published'] += 1
                            audit.update(side=side, topic=pubs[kind].topic_name, sdk_sha256=digest,
                                         counters=dict(reader.counts[kind]))
                            metadata.publish(String(data=json.dumps(audit)))
                            last_good = time.monotonic()
                        except Exception as exc:
                            reader.counts[kind]['publish_errors'] += 1
                            reader.errors[kind] = 'publish: '+str(exc)[:180]
                    if time.monotonic()-last_good > 5:
                        raise RuntimeError('no valid field published for 5 seconds')
                except Exception as exc:
                    error = str(exc)[:240]
                    if sensor is not None:
                        try:
                            sensor.disconnect()
                        except Exception:
                            pass
                    sensor, retry_at = None, time.monotonic()+5
                    reconnects += 1
            if tick-last_status >= 1:
                status.publish(String(data=json.dumps(dict(schema_version=4,
                    acquisition='independent-field-v1', state='streaming' if sensor else 'retrying',
                    error=error, host_timestamp_ns=time.time_ns(), reconnects=reconnects,
                    fields={k: dict(counters=dict(reader.counts[k]), error=reader.errors.get(k, ''),
                        last_valid_read_ns=reader.last_good_ns.get(k)) for k in reader.kinds},
                    note='unframed force read rate is NOT device update rate'))))
                last_status = tick
            # Poll framed getters faster than their source; publish only new IDs.
            # Matching two independent 30 Hz clocks causes duplicate/skip aliasing.
            rclpy.spin_once(node, timeout_sec=max(0., 1/(2*tac['fps'])-(time.monotonic()-tick)))
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if sensor is not None:
            try:
                sensor.disconnect()
            except Exception:
                pass
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
