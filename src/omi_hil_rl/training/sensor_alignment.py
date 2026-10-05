"""Offline per-field provenance; independent acquisition, causal alignment.

Host header skew is a diagnostic, not proof of simultaneous device exposure.
Old bags without metadata remain readable with explicitly unknown source IDs.
"""
from collections import OrderedDict
import json
import math

from .stack_shadow import StackObservations


def read_sensor_metadata(bag):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from std_msgs.msg import String
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id=''), rosbag2_py.ConverterOptions('', ''))
    topics = ['/omi/wrist/metadata'] + [f'/omi/tactile_grid24x16/{s}/metadata' for s in 'ab']
    reader.set_filter(rosbag2_py.StorageFilter(topics=topics))
    records = {}
    while reader.has_next():
        topic, payload, _ = reader.read_next()
        try:
            row = json.loads(deserialize_message(payload, String).data)
            if row.get('schema_version') != 4:
                continue
            key = 'wrist_rgb' if topic == '/omi/wrist/metadata' else row['side']+'_'+row['field']
            header = int(row['header_ns'])
            if header <= 0:
                continue
            records[key, header] = {k: row.get(k) for k in (
                'sdk_frame_id', 'source_timestamp_ns', 'timestamp_kind', 'host_read_started_ns',
                'host_read_finished_ns', 'freshness_verified', 'changed_since_previous_read')}
        except (ValueError, KeyError, TypeError):
            continue
    return records


def prefer_record_topic(runtime, available):
    """Choose exactly one wrist stream, never merge live and recording copies."""
    for topic, key in list(runtime.topics.items()):
        if key == 'wrist_rgb' and topic+'/record' in available:
            del runtime.topics[topic]
            runtime.topics[topic+'/record'] = key


def add_wrench_alignment(status, aligned, provenance, reference):
    history = status.get('field_alignment_history')
    if history is None:
        return
    for slot, fields in enumerate(history):
        t = reference-(9-slot)*100_000_000
        for side, name in enumerate('ab'):
            rx = int(aligned['wrench_receive_ns'][slot, side])
            header = int(aligned['wrench_header_ns'][slot, side])
            row = dict(receive_ns=rx or None, header_ns=header or None,
                valid=bool(aligned['wrench_mask'][slot, side]),
                receive_age_ms=(t-rx)/1e6 if rx else None,
                header_age_ms=(t-header)/1e6 if header else None,
                sdk_frame_id=None, source_timestamp_ns=None,
                timestamp_kind='legacy_force_header_unverified', freshness_verified=False)
            row.update(provenance.get((name+'_wrench', header), {}))
            fields[name+'_wrench'] = row


class AuditedObservations(StackObservations):
    def __init__(self, *args, provenance=None, max_tactile_skew_ms=None, **kwargs):
        if max_tactile_skew_ms is not None and (not math.isfinite(max_tactile_skew_ms) or max_tactile_skew_ms < 0):
            raise ValueError('max tactile skew must be finite and nonnegative')
        self.provenance = provenance or {}
        self.max_tactile_skew_ns = None if max_tactile_skew_ms is None else max_tactile_skew_ms*1e6
        super().__init__(*args, **kwargs)

    def reset(self):
        super().reset()
        self.source_records = {}
        self.alignment_history = OrderedDict()

    def ingest(self, key, msg, receive_ns):
        accepted = super().ingest(key, msg, receive_ns)
        if accepted:
            rows = self.source_records.setdefault(key, OrderedDict())
            rows[receive_ns] = dict(self.latest[key])
            while len(rows) > 512:
                rows.popitem(last=False)
        return accepted

    def window(self, reference_ns):
        window, status = super().window(reference_ns)
        selected = {}
        for key, rx in status.get('source_receive_ns', {}).items():
            row = self.source_records.get(key, {}).get(rx, {})
            header = row.get('header_ns')
            selected[key] = dict(receive_ns=rx, header_ns=header, valid=True,
                receive_age_ms=(reference_ns-rx)/1e6,
                header_age_ms=None if header is None else (reference_ns-header)/1e6,
                sdk_frame_id=None, source_timestamp_ns=None,
                timestamp_kind='legacy_header_semantics_unverified', freshness_verified=False)
            limit = self.contract['eef_max_age_ns'] if key == 'eef' else self.contract['max_age_ns']
            selected[key]['header_within_age_limit'] = (header is not None and
                -self.contract['ingress_max_header_ahead_ns'] <= reference_ns-header <= limit)
            selected[key].update(self.provenance.get((key, header), {}))
        stamps = [r['header_ns'] for k, r in selected.items()
                  if k.startswith(('a_', 'b_')) and r['header_ns'] is not None]
        skew = max(stamps)-min(stamps) if stamps else None
        status['field_alignment'] = selected
        status['tactile_host_header_skew_ms'] = None if skew is None else skew/1e6
        status['max_tactile_host_header_skew_ms'] = (None if self.max_tactile_skew_ns is None
                                                     else self.max_tactile_skew_ns/1e6)
        if window is not None and self.max_tactile_skew_ns is not None and skew is not None and skew > self.max_tactile_skew_ns:
            self.history.pop(reference_ns, None)
            window = None
            status['reason'] = 'tactile_host_header_skew'
        self.alignment_history[reference_ns] = selected if window is not None else {}
        for t in list(self.alignment_history):
            if t < reference_ns-900_000_000:
                del self.alignment_history[t]
        status['field_alignment_history'] = [self.alignment_history.get(reference_ns-(9-i)*100_000_000, {})
                                             for i in range(10)]
        return window, status
