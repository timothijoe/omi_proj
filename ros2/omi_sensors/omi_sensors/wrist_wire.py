"""OMI MJPG/FCP1 client wire format, based on vendor camera_proxy.proto.

Reference: diamond/daimon_stuff/dm_gripper_cam_py (2026-10-03).
No import of that external workspace; only the compatible protocol is implemented.
"""
import math
import struct
import time
import uuid

HEADER = struct.Struct('!4sB16sQdIHHHBB')


def message_types():
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    file = descriptor_pb2.FileDescriptorProto(name='omi_wrist_wire.proto', package='omi.wrist', syntax='proto3')
    definitions = {
        'StreamRequest': [('codec', 1, 9), ('width', 2, 5), ('height', 3, 5), ('fps', 4, 5),
                          ('udp_port', 5, 5), ('client_ip', 6, 9), ('device', 7, 9), ('max_datagram', 8, 5)],
        'StreamEvent': [('type', 1, 5), ('session_id', 2, 9), ('message', 3, 9), ('codec', 4, 9),
                        ('width', 5, 5), ('height', 6, 5), ('fps', 7, 5), ('device', 8, 9)],
        'StopStreamRequest': [('session_id', 1, 9)],
        'StopStreamResponse': [('stopped', 1, 8), ('message', 2, 9)],
    }
    for name, fields in definitions.items():
        msg = file.message_type.add(name=name)
        for field, number, kind in fields:
            msg.field.add(name=field, number=number, type=kind, label=1)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return {name: message_factory.GetMessageClass(pool.FindMessageTypeByName('omi.wrist.' + name))
            for name in definitions}


class Reassembler:
    """At most four incomplete JPEGs, 4 MiB each, expiring after 200 ms."""
    def __init__(self, session):
        self.session = uuid.UUID(session).bytes
        self.frames = {}
        self.last_id = -1

    def push(self, packet, now=None):
        now = time.monotonic() if now is None else now
        self.frames = {k: v for k, v in self.frames.items() if now - v[0] < .2}
        if len(packet) < HEADER.size:
            raise ValueError('short FCP1 packet')
        magic, version, session, fid, stamp, size, idx, count, length, codec, flags = HEADER.unpack_from(packet)
        payload = packet[HEADER.size:]
        if session != self.session or fid <= self.last_id:
            return None
        if (magic != b'FCP1' or version != 1 or codec != 1 or not math.isfinite(stamp)
                or not 0 < size <= 4 * 1024**2 or not 0 < count <= 4096
                or idx >= count or len(payload) != length or not length):
            raise ValueError('invalid MJPG FCP1 packet')
        if fid not in self.frames:
            if len(self.frames) >= 4:
                self.frames.pop(min(self.frames, key=lambda k: self.frames[k][0]))
            self.frames[fid] = (now, size, count, stamp, {})
        state = self.frames[fid]
        if state[1:4] != (size, count, stamp):
            self.frames.pop(fid)
            raise ValueError('inconsistent frame metadata')
        state[4][idx] = payload
        if sum(map(len, state[4].values())) > size:
            self.frames.pop(fid)
            raise ValueError('oversized frame')
        if len(state[4]) != count:
            return None
        data = b''.join(state[4][i] for i in range(count))
        self.frames.pop(fid)
        if len(data) != size:
            raise ValueError('incorrect JPEG size')
        self.last_id = fid
        self.frames = {k: v for k, v in self.frames.items() if k > fid}
        return fid, stamp, data
