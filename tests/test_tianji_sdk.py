import numpy as np
import pytest

from omi_hil_rl.hardware.tianji_sdk import TianjiConfig, TianjiSdkArm


LIMITS = ((-90.0, 90.0),) * 7  # Fake-SDK test limits; not real Tianji limits.


class FakeSdk:
    def __init__(self):
        self.frame = 0
        self.state = 0
        self.error = 0
        self.calls = []
        self.joints = [0.0] * 7

    def connect(self, ip):
        self.calls.append(("connect", ip))
        return True

    def subscribe(self, _):
        self.frame += 1
        return {
            "outputs": [{"fb_joint_pos": self.joints, "frame_serial": self.frame}] * 2,
            "states": [{"cur_state": self.state, "err_code": self.error}] * 2,
        }

    def set_position_state(self, arm, vel_ratio, acc_ratio):
        self.calls.append(("mode", arm, vel_ratio, acc_ratio))
        self.state = 1
        return True

    def set_joint_position_cmd(self, arm, joint):
        self.calls.append(("target", arm, joint))
        return True

    def soft_stop(self, arm):
        self.calls.append(("stop", arm))

    def disable(self, arm):
        self.calls.append(("disable", arm))
        return True

    def release_robot(self):
        self.calls.append(("release",))


class RejectingSdk(FakeSdk):
    def set_joint_position_cmd(self, arm, joint):
        self.calls.append(("rejected_target", arm))
        return False


def config(**kwargs):
    data = dict(robot_ip="test-only", arm="A", joint_limits_deg=LIMITS,
                max_step_deg=0.5, vel_ratio=10, acc_ratio=10)
    data.update(kwargs)
    return TianjiConfig(**data)


def test_connect_is_read_only_and_motion_requires_explicit_authorization():
    sdk = FakeSdk()
    arm = TianjiSdkArm(config(), sdk_factory=lambda: sdk, dcss_factory=object)
    assert arm.connect().frame_serial == 1
    assert [call[0] for call in sdk.calls] == ["connect"]
    with pytest.raises(PermissionError):
        arm.arm_position_mode()
    arm.close()
    assert [call[0] for call in sdk.calls] == ["connect", "release"]


def test_authorized_target_converts_radians_and_checks_step_and_limits():
    sdk = FakeSdk()
    arm = TianjiSdkArm(config(motion_authorized=True), sdk_factory=lambda: sdk, dcss_factory=object)
    arm.connect()
    arm.arm_position_mode()
    target = np.zeros(7)
    target[0] = np.deg2rad(0.2)
    arm.send_joint_target_rad(target)
    assert sdk.calls[-1][0:2] == ("target", "A")
    assert sdk.calls[-1][2][0] == pytest.approx(0.2)
    with pytest.raises(ValueError, match="single-step"):
        arm.send_joint_target_rad(np.array([np.deg2rad(0.6)] + [0] * 6))
    with pytest.raises(ValueError, match="joint limits"):
        arm.send_joint_target_rad(np.array([np.deg2rad(91)] + [0] * 6))
    arm.stop()
    with pytest.raises(RuntimeError, match="not armed"):
        arm.send_joint_target_rad(target)
    arm.close()


def test_invalid_site_limits_rejected_before_sdk_exists():
    with pytest.raises(ValueError, match="joint_limits"):
        config(joint_limits_deg=((0, 1),))


def test_rejected_command_latches_fault_and_attempts_software_stop():
    sdk = RejectingSdk()
    arm = TianjiSdkArm(config(motion_authorized=True), sdk_factory=lambda: sdk, dcss_factory=object)
    arm.connect()
    arm.arm_position_mode()
    with pytest.raises(RuntimeError, match="rejected joint target"):
        arm.send_joint_target_rad(np.zeros(7))
    assert [call[0] for call in sdk.calls[-3:]] == ["rejected_target", "stop", "disable"]
    with pytest.raises(RuntimeError, match="not armed"):
        arm.send_joint_target_rad(np.zeros(7))
    arm.close()


def test_controller_error_while_armed_attempts_software_stop():
    sdk = FakeSdk()
    arm = TianjiSdkArm(config(motion_authorized=True), sdk_factory=lambda: sdk, dcss_factory=object)
    arm.connect()
    arm.arm_position_mode()
    sdk.error = 17
    with pytest.raises(RuntimeError, match="controller error: 17"):
        arm.read_state()
    assert [call[0] for call in sdk.calls[-2:]] == ["stop", "disable"]
    arm.close()
