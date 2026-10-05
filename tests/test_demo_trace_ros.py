"""ROS message and bag checks in an isolated domain; no robot command topic used."""
from dataclasses import replace
import json
import sqlite3
import time
from types import SimpleNamespace

import numpy as np
import pytest

rclpy = pytest.importorskip("rclpy")
from rclpy.serialization import deserialize_message
from std_msgs.msg import Float64MultiArray, String

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.demo import RawBag, recording_topics
from omi_hil_rl.hil.ros_transport import RosTransport
from omi_hil_rl.real.sdk_action import output_action


def test_wire_topic_and_label_trace_share_id_and_exact_action():
    transport = RosTransport.__new__(RosTransport)
    transport.config = HILConfig(transport="ros")
    transport.topic = "/isolated_test/command"
    transport.convention = transport.config.sdk_convention
    transport.last_owner = "human"
    transport.command_anchor_ns = 100
    messages, traces = [], []
    transport.publisher = SimpleNamespace(publish=messages.append)
    transport.trace_publisher = SimpleNamespace(publish=traces.append)
    transport.node = SimpleNamespace(count_publishers=lambda topic: 0 if "manual_decision" in topic else 1,
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=110)))
    action = transport.config.physical_action(np.full(6, .3, np.float32))
    wire = transport._publish(action, "hil:paired")
    trace = json.loads(traces[0].data)
    assert type(wire) is list
    assert messages[0].layout.dim[0].label == trace["command_id"] == "hil:paired"
    assert trace["action_source"] == "human" and trace["label_candidate"]
    assert trace["command_topic"] == transport.topic
    assert wire == list(messages[0].data) == trace["wire_action"] == output_action(action, transport.convention)
    np.testing.assert_array_equal(trace["action_m_rad"], action)
    transport._publish(np.zeros(6))
    stop = json.loads(traces[-1].data)
    assert not stop["label_candidate"] and stop["action_source"] == "stop"


def test_raw_bag_preserves_sent_command_and_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("ROS_DOMAIN_ID", "231")
    rclpy.init()
    node = rclpy.create_node("omi_demo_bag_test")
    topic, trace_topic = "/omi_demo_test/command", "/omi_demo_test/trace"
    command_publisher = node.create_publisher(Float64MultiArray, topic, 10)
    trace_publisher = node.create_publisher(String, trace_topic, 10)
    bag = None
    try:
        bag = RawBag(tmp_path, [topic, trace_topic])
        bag.wait_subscriptions(node, {topic: 0, trace_topic: 0})
        for _ in range(5):
            command_publisher.publish(Float64MultiArray(data=[1., 2., 3., 4., 5., 6.]))
            trace_publisher.publish(String(data=json.dumps(dict(command_topic=topic, action_m_rad=[.001, .002, .003, 0., 0., 0.]))))
            rclpy.spin_once(node, timeout_sec=.05)
        time.sleep(.2)
    finally:
        if bag:
            bag.close()
        node.destroy_node()
        rclpy.shutdown()
    coverage = json.loads((tmp_path / "raw_recording.json").read_text())
    assert coverage["metadata_present"] and not coverage["requested_without_messages"]
    with sqlite3.connect(next((tmp_path / "raw").glob("*.db3"))) as db:
        rows = db.execute("SELECT topics.name, messages.data FROM messages JOIN topics ON topics.id=messages.topic_id").fetchall()
    commands = [deserialize_message(data, Float64MultiArray) for name, data in rows if name == topic]
    traces = [deserialize_message(data, String) for name, data in rows if name == trace_topic]
    assert commands and traces
    assert list(commands[0].data) == [1., 2., 3., 4., 5., 6.]
    assert json.loads(traces[0].data)["command_topic"] == topic


def test_default_recording_list_includes_actual_control_channels():
    topics = recording_topics(["/camera/camera/color/image_raw"], command_topic="/custom/output")
    assert set(["/omi/action/decision", "/omi/action/manual_decision", "/omi/action/command_trace",
                "/omi/action/receipt", "/custom/output", "/camera/camera/color/image_raw"]) <= set(topics)


def test_snapshot_over_dds_is_convertible_without_session_files(tmp_path, monkeypatch):
    """Record actual self-contained snapshot payload, then extract using only bag."""
    from omi_hil_rl.hil.demo import collect
    from omi_hil_rl.hil.demo_bag import SAMPLE_TOPIC, encode_sample, bag_records, convert_records
    from rclpy.duration import Duration
    manifests=collect(tmp_path/'capture',HILConfig(),episodes=1,fake_steps=2)
    manifest=manifests[0]
    # Nontrivial image bytes exercise large-message transport rather than empty images.
    rng=np.random.default_rng(11)
    path=tmp_path/'capture'/'episodes'/manifest['episode']/'000000.npz'
    with np.load(path,allow_pickle=False) as archive:arrays={k:archive[k] for k in archive.files}
    arrays['observation__rgb']=rng.integers(0,256,size=(10,3,128,128),dtype=np.uint8)
    np.savez_compressed(path,**arrays)
    monkeypatch.setenv('ROS_DOMAIN_ID','231')
    rclpy.init();node=rclpy.create_node('omi_snapshot_bag_test')
    sample=node.create_publisher(String,SAMPLE_TOPIC,10)
    event=node.create_publisher(String,'/omi/demo/event',10)
    target=tmp_path/'recording';target.mkdir();bag=None
    try:
        bag=RawBag(target,[SAMPLE_TOPIC,'/omi/demo/event'])
        bag.wait_subscriptions(node,{SAMPLE_TOPIC:0,'/omi/demo/event':0})
        for i in range(2):
            source=path.parent/f'{i:06d}.npz'
            sample.publish(String(data=json.dumps(encode_sample(manifest['episode'],i,source))))
        event.publish(String(data=json.dumps(dict(kind='episode_end',**manifest))))
        assert sample.wait_for_all_acked(Duration(seconds=5))
        assert event.wait_for_all_acked(Duration(seconds=5))
    finally:
        if bag:bag.close()
        node.destroy_node();rclpy.shutdown()
    report=convert_records(bag_records(target/'raw'),tmp_path/'converted',source=target/'raw')
    assert report['samples']==2
    assert (tmp_path/'converted'/'episodes'/manifest['episode']/'000000.npz').read_bytes()==path.read_bytes()
