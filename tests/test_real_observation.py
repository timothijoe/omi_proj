from types import SimpleNamespace

import numpy as np
import pytest

from omi_hil_rl.real.observation import (
    DEFAULT_SENSOR_GROUPS,
    ObservationConfig,
    ObservationNotReady,
    SquareRoi,
    TianjiInsertionObservationBuilder,
    TimedSample,
    TimestampedBuffer,
    _crop_square_resize_nearest,
)
from omi_hil_rl.real.ros_topics import (
    RosTopicIngestor,
    TianjiTopicNames,
    decode_image_message,
    joint_feedback_value,
)


def test_timestamped_buffer_selects_latest_past_sample_when_callbacks_are_out_of_order():
    buffer = TimestampedBuffer(capacity=2)
    buffer.append(TimedSample(30, 31, "late"))
    buffer.append(TimedSample(10, 11, "early"))
    buffer.append(TimedSample(20, 21, "middle"))

    assert buffer.oldest_timestamp_ns == 20
    assert buffer.latest_at(29).value == "middle"
    assert buffer.latest_at(30).value == "late"


def image_message(array: np.ndarray, encoding: str, *, padding: int = 0):
    if encoding in {"rgb8", "bgr8"}:
        pixel_bytes = array.shape[1] * 3
    else:
        pixel_bytes = array.shape[1] * array.dtype.itemsize
    rows = []
    for row in array:
        rows.append(row.tobytes() + bytes(padding))
    return SimpleNamespace(
        height=array.shape[0],
        width=array.shape[1],
        encoding=encoding,
        is_bigendian=False,
        step=pixel_bytes + padding,
        data=b"".join(rows),
    )


def test_image_decoder_handles_bgr_padding_and_float_depth():
    bgr = np.asarray([[[1, 2, 3], [4, 5, 6]]], dtype=np.uint8)
    decoded = decode_image_message(image_message(bgr, "bgr8", padding=2))
    np.testing.assert_array_equal(decoded, [[[3, 2, 1], [6, 5, 4]]])

    depth = np.asarray([[0.25, 1.5], [2.0, 4.0]], dtype=np.float32)
    decoded_depth = decode_image_message(image_message(depth, "32FC1", padding=4))
    np.testing.assert_allclose(decoded_depth, depth)


def feed_complete_sample(builder: TianjiInsertionObservationBuilder, timestamp_ns: int, offset: float = 0.0):
    builder.push(
        "joint",
        {
            "position": np.arange(7, dtype=np.float32) + offset,
            "velocity": np.ones(7, dtype=np.float32),
            "effort": np.full(7, 2, dtype=np.float32),
        },
        source_timestamp_ns=timestamp_ns,
    )
    builder.push("gripper", 0.5 + offset, source_timestamp_ns=timestamp_ns)
    builder.push("external_rgb", np.full((4, 5, 3), 10, dtype=np.uint8), source_timestamp_ns=timestamp_ns)
    builder.push("wrist_rgb", np.full((6, 7, 3), 20, dtype=np.uint8), source_timestamp_ns=timestamp_ns)
    builder.push("tactile_a_raw", np.full((3, 4), 30, dtype=np.uint8), source_timestamp_ns=timestamp_ns)
    builder.push("tactile_b_raw", np.full((3, 4), 40, dtype=np.uint8), source_timestamp_ns=timestamp_ns)
    builder.push("tactile_a_depth", np.full((3, 4), 1.0 + offset, dtype=np.float32), source_timestamp_ns=timestamp_ns)
    builder.push("tactile_b_depth", np.full((3, 4), 2.0 + offset, dtype=np.float32), source_timestamp_ns=timestamp_ns)
    builder.push("tactile_a_force", np.arange(6, dtype=np.float32) + offset, source_timestamp_ns=timestamp_ns)
    builder.push("tactile_b_force", np.arange(6, dtype=np.float32) + 10 + offset, source_timestamp_ns=timestamp_ns)


def test_builder_produces_fixed_network_observation_and_subtracts_grasp_baseline():
    builder = TianjiInsertionObservationBuilder(
        ObservationConfig(external_rgb_shape=(2, 3), wrist_rgb_shape=(3, 2), tactile_shape=(2, 2))
    )
    baseline_time = 1_000_000_000
    feed_complete_sample(builder, baseline_time)
    builder.capture_grasp_baseline(baseline_time)
    next_time = baseline_time + 100_000_000
    feed_complete_sample(builder, next_time, offset=0.25)

    observation = builder.build(next_time)

    assert builder.observation_space.contains(observation)
    assert observation["state"].shape == (22,)
    assert observation["external_rgb"].shape == (2, 3, 3)
    assert observation["external_rgb_roi_offset_px"].shape == (2,)
    assert observation["wrist_rgb"].shape == (3, 2, 3)
    assert observation["tactile_raw"].shape == (2, 2, 2)
    np.testing.assert_allclose(observation["wrench_delta"], 0.25)
    np.testing.assert_allclose(observation["tactile_depth_delta"], 0.25)
    np.testing.assert_allclose(observation["sensor_age_s"], 0)
    np.testing.assert_array_equal(observation["sensor_valid"], 1)


def test_default_camera_rois_match_record010_and_wrist_is_horizontally_centered():
    config = ObservationConfig()
    head = np.zeros((480, 640, 3), dtype=np.uint8)
    wrist = np.zeros((1080, 1920, 3), dtype=np.uint8)

    _, head_bounds = _crop_square_resize_nearest(head, config.external_rgb_roi, (128, 128))
    _, wrist_bounds = _crop_square_resize_nearest(wrist, config.wrist_rgb_roi, (128, 128))

    assert head_bounds == (228, 108, 192)
    assert wrist_bounds == (766, 566, 389)
    head_left, head_top, head_side = head_bounds
    np.testing.assert_allclose(
        [head_left + head_side / 2 - 640 / 2, head_top + head_side / 2 - 480 / 2],
        [4, -36],
    )
    assert config.wrist_rgb_roi == SquareRoi(0.5, 0.704, 0.36)


def test_builder_rejects_missing_baseline_and_stale_required_sensor():
    builder = TianjiInsertionObservationBuilder(ObservationConfig(max_age_s=0.05))
    timestamp = 1_000_000_000
    feed_complete_sample(builder, timestamp)
    with pytest.raises(ObservationNotReady, match="baseline"):
        builder.build(timestamp)
    builder.capture_grasp_baseline(timestamp)
    with pytest.raises(ObservationNotReady, match="stale"):
        builder.build(timestamp + 100_000_000)


def test_ros_ingestor_maps_record010_topics_without_importing_ros():
    builder = TianjiInsertionObservationBuilder()
    ingestor = RosTopicIngestor(builder)
    topics = TianjiTopicNames()
    stamp = SimpleNamespace(sec=2, nanosec=3)
    header = SimpleNamespace(stamp=stamp)
    message = SimpleNamespace(
        header=header,
        arm_positions=list(range(14)),
        arm_velocities=list(range(14, 28)),
        arm_efforts=list(range(28, 42)),
    )
    ingestor.ingest(topics.joint_feedback, message, received_timestamp_ns=2_000_000_010)

    value = builder.buffers["joint"].latest_at(2_000_000_003).value
    np.testing.assert_array_equal(value["position"], np.arange(7))
    assert set(ingestor.subscribed_topics) == set(topics.sensor_for_topic())


def test_joint_feedback_rejects_wrong_shape():
    message = SimpleNamespace(arm_positions=[0] * 7, arm_velocities=[0] * 14, arm_efforts=[0] * 14)
    with pytest.raises(ValueError, match="left and right"):
        joint_feedback_value(message)


def test_torch_adapter_creates_batched_channel_first_images():
    torch = pytest.importorskip("torch")
    from omi_hil_rl.real.tensor_adapter import observation_to_torch

    observation = {
        "external_rgb": np.zeros((8, 9, 3), dtype=np.uint8),
        "state": np.ones(22, dtype=np.float32),
    }
    result = observation_to_torch(observation)
    assert result["external_rgb"].shape == (1, 3, 8, 9)
    assert result["external_rgb"].dtype == torch.float32
    assert result["state"].shape == (1, 22)
