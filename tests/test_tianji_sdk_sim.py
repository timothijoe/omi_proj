"""Exercise the Tianji SDK boundary against MuJoCo, without vendor hardware."""

import mujoco
import numpy as np

from omi_hil_rl.hardware.tianji_sdk import TianjiConfig, TianjiSdkArm
from omi_hil_rl.sim.tianji_surrogate import TianjiSurrogateEnv


class MujocoSdkDouble:
    def __init__(self):
        self.env = TianjiSurrogateEnv()
        self.frame = 0
        self.state = 0
        self.connected = False

    def connect(self, _ip):
        self.connected = True
        return True

    def subscribe(self, _dcss):
        mujoco.mj_step(self.env.model, self.env.data)
        self.frame += 1
        position_deg = np.rad2deg(self.env.data.qpos[self.env.qpos_ids]).tolist()
        output = {"fb_joint_pos": position_deg, "frame_serial": self.frame}
        status = {"cur_state": self.state, "err_code": 0}
        return {"outputs": [output, output], "states": [status, status]}

    def set_position_state(self, arm, _vel, _acc):
        assert arm == "A"
        self.state = 1
        return True

    def set_joint_position_cmd(self, arm, joints_deg):
        assert arm == "A"
        self.env.data.ctrl[self.env.actuator_ids] = np.deg2rad(joints_deg)
        for _ in range(50):
            mujoco.mj_step(self.env.model, self.env.data)
        return True

    def soft_stop(self, _arm):
        self.env.data.ctrl[self.env.actuator_ids] = self.env.data.qpos[self.env.qpos_ids]

    def disable(self, _arm):
        self.state = 0
        return True

    def release_robot(self):
        self.connected = False
        self.env.close()


def test_sdk_adapter_sends_degree_command_to_mujoco_and_reads_radians():
    sdk = MujocoSdkDouble()
    limits = tuple(tuple(pair) for pair in np.rad2deg(sdk.env.joint_limits))
    config = TianjiConfig(
        robot_ip="sim-only", arm="A", joint_limits_deg=limits,
        max_step_deg=0.5, vel_ratio=10, acc_ratio=10, motion_authorized=True,
    )
    arm = TianjiSdkArm(config, sdk_factory=lambda: sdk, dcss_factory=object)
    initial = arm.connect()
    assert initial.joint_position_rad.shape == (7,)
    arm.arm_position_mode()
    target = np.zeros(7)
    target[0] = np.deg2rad(0.2)
    arm.send_joint_target_rad(target)
    after = arm.read_state()
    assert 0 < after.joint_position_rad[0] <= target[0] + 1e-3
    arm.stop()
    arm.close()
    assert not sdk.connected
