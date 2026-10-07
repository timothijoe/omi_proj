#!/usr/bin/env python3
"""
接收 10Hz 六维增量话题 (X Y Z RX RY RZ, mm/度)，
以 200Hz 控制频率转换为关节角指令控制天机 (Marvin) 机械臂。

流程:
  1. 连接机械臂后先标定 TCP: 调用 TcpForceKine.calibrate_tcp_tool()
     (移植自 FX_Robot_Kine_CalibrateTcpTool)。默认 identity 标定 (TCP=法兰);
     传入 tool_xyzabc 参数则按手量工具尺寸标定, 增量作用在标定出的 TCP 上
  2. OMI 默认不连接；显式授权连接后沿用原版 start_mode=3（关节阻抗）
  3. 订阅 /omi/action/decision (std_msgs/Float64MultiArray,
     data = [X, Y, Z, RX, RY, RZ])
  话题控制: 手柄和策略分别将增量乘以各自的 command_rate 换算为速度。
  200Hz 每周期按速度 / ctrl_rate 做一次 IK、限幅与包络检查后立即下发。
  持续保持最近速度, 直到新速度、零指令、断流超时或运动保护触发。
  策略保留触觉保护与后退速度限制; 手动输入沿用原有保护边界。
  delta_splits 为兼容保留, 不再决定话题控制的步长或执行时长。

依赖: Arm_control SDK，由 ARM_SDK_DIR 指定；仅授权连接时导入。
来源及迁移差异见 tutorials/robot_controller.md；原始副本保存在 local/vendor。
"""

import math
import json
import os
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.clock import Clock, ClockType
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Float64MultiArray, String
from std_srvs.srv import Trigger
from marvin_msgs.msg import Jointfeedback
from geometry_msgs.msg import PoseStamped, WrenchStamped
from .tactile_guard import TactileGuard
import tf2_ros
from geometry_msgs.msg import TransformStamped

# Vendor modules are loaded only after explicit motion authorization.
# The original SDK remains outside Git, under local/vendor/optical_module_pu.
FRAME_BASE = 0
FRAME_TCP = 1


# ---------- 安全防护 ----------
# 指令-反馈偏差监护: 任一关节指令与反馈偏差超过该值(度)持续超限即停发。
# 防止指令迭代从错误起点出发后一路错下去。
MAX_CMD_FB_ERR_DEG = 15.0
# 连续偏差超限次数达到即触发停发(排除瞬时抖动)
CMD_FB_ERR_STRIKES = 10

# 机械臂状态枚举 (SDK ARM_STATE_*)
STATE_POSITION = 1      # 位置跟随
STATE_TORQUE = 3        # 扭矩 (关节阻抗需在此状态 + imp_type=1)


class DeltaCtrlNode(Node):
    def __init__(self):
        super().__init__('delta_ctrl_node')

        # ---------- 参数 ----------
        self.declare_parameter('robot_ip', '192.168.14.190')
        self.declare_parameter('arm', 'A')              # A / B
        self.declare_parameter('delta_topic', '/omi/action/decision')
        self.declare_parameter('manual_delta_topic', '/omi/action/manual_decision')
        self.declare_parameter('hil_manual_receipts', True)  # tagged human-collection protocol
        self.declare_parameter('ctrl_rate', 200.0)      # Hz
        self.declare_parameter('policy_command_rate', 10.0)  # Hz, 策略增量对应的输入周期
        self.declare_parameter('manual_command_rate', 10.0)  # Hz, 手柄增量对应的输入周期
        self.declare_parameter('manual_timeout', 0.25)      # s, 速度保持的断流期限
        self.declare_parameter('delta_timeout', 0.25)    # s, 超时无增量则停止发送
        self.declare_parameter('max_step_deg', 2.0)     # 单步目标最大关节角步进(度), 安全限幅
        self.declare_parameter('enable_publish_joint_state', True)
        # 末端工具位姿发布频率 (Hz), 0=不发布 /tj/info/eef_left
        self.declare_parameter('eef_publish_rate', 50.0)
        self.declare_parameter('connect_on_start', False)
        self.declare_parameter('motion_authorized', False)
        # 每条 /delta_cmd 切分的子增量个数 (200Hz 下发, 20 步 = 10Hz 增量的 0.1s)
        self.declare_parameter('delta_splits', 20)
        # 增量表达坐标系: 'base'=沿机器人 Base 轴; 'tcp'=沿当前 TCP 自身轴
        self.declare_parameter('delta_frame', 'base')
        # Opt-in, policy-only guard. Manual input has a separate trusted topic.
        self.declare_parameter('tactile_guard_enabled', False)
        self.declare_parameter('tactile_force_limit', 2.0)
        self.declare_parameter('tactile_torque_limit', 0.5)
        self.declare_parameter('tactile_timeout', 0.2)
        self.declare_parameter('tactile_retreat_step_mm', 0.2)
        self.declare_parameter('tactile_retreat_speed_mm_s', 2.0)
        # TCP 标定: 'identity'=TCP 与法兰重合 (无视觉输入时的默认);
        # 'measure'=用 tool_xyzabc 参数 (法兰系 [x,y,z,A,B,C], mm/度) 手量标定
        self.declare_parameter('calib_mode', 'identity')
        self.declare_parameter('tool_xyzabc', [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        # 工作空间包络半径 (mm): TCP 相对启动位置超出该球形范围则拒绝增量, 0=禁用
        self.declare_parameter('envelope_radius_mm', 100.0)
        # 启动模式: 3=关节阻抗 (低刚度, 末端可手推柔顺), 1=位置跟随
        self.declare_parameter('start_mode', 3)
        # 关节阻抗模式 K/D (set_joint_kd_params: K 单位 N·m/deg 范围 0~22,
        # D 建议 0.3 左右)
        self.declare_parameter('imp_k', [6.0, 6.0, 6.0, 5.0, 3.0, 3.0, 2.0])
        self.declare_parameter('imp_d', [0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3])
        # eef 位姿表达坐标系: FK 只能给出臂基坐标系位姿, 机器人根坐标系
        # (如 base_link) 与臂基之间存在安装偏移, 通过 /tf 查询 root_frame ->
        # arm_base_frame 的变换并左乘 (发布 /tj/info/eef_left 用)。
        # arm_base_frame 留空则按 arm 参数自动推断: A->Base_L, B->Base_R
        self.declare_parameter('root_frame', 'base_link')
        self.declare_parameter('arm_base_frame', '')
        # base_link -> 臂基安装变换来源:
        #   'urdf'   = 按 Stand URDF J1 安装姿态/高度发布静态 TF; 左臂 Y 已修正
        #              (左: xyz(0, 0.0260, 1.121) rpy(-90°,0,0), Y 为现场修正值;
        #               右: xyz(0, -0.2005, 1.121) rpy(+90°,0,0))
        #   'none'   = 不发布, 依赖外部节点提供 root_frame -> arm_base_frame
        self.declare_parameter('publish_root_tf', 'urdf')

        self.robot_ip = self.get_parameter('robot_ip').value
        self.arm = self.get_parameter('arm').value
        self.delta_topic = self.get_parameter('delta_topic').value
        self.manual_delta_topic = self.get_parameter('manual_delta_topic').value
        if self.manual_delta_topic == self.delta_topic:
            raise ValueError('manual_delta_topic and delta_topic must differ')
        self.ctrl_rate = float(self.get_parameter('ctrl_rate').value)
        self.delta_timeout = float(self.get_parameter('delta_timeout').value)
        self.policy_command_rate = float(self.get_parameter('policy_command_rate').value)
        self.manual_command_rate = float(self.get_parameter('manual_command_rate').value)
        self.manual_timeout = float(self.get_parameter('manual_timeout').value)
        self.max_step_deg = float(self.get_parameter('max_step_deg').value)
        self.delta_splits = int(self.get_parameter('delta_splits').value)
        self.pub_js = bool(self.get_parameter('enable_publish_joint_state').value)
        self.connect_on_start = bool(self.get_parameter('connect_on_start').value)
        self.motion_authorized = bool(self.get_parameter('motion_authorized').value)
        if self.connect_on_start and not self.motion_authorized:
            raise ValueError('connect_on_start requires motion_authorized=true: startup changes robot mode')
        self.delta_frame = str(self.get_parameter('delta_frame').value).lower()
        self.tactile_guard = TactileGuard(
            enabled=bool(self.get_parameter('tactile_guard_enabled').value),
            force_limit=float(self.get_parameter('tactile_force_limit').value),
            torque_limit=float(self.get_parameter('tactile_torque_limit').value),
            timeout=float(self.get_parameter('tactile_timeout').value),
            retreat_step_mm=float(self.get_parameter('tactile_retreat_step_mm').value))
        if self.tactile_guard.enabled and self.delta_frame != 'base':
            raise ValueError('tactile guard requires delta_frame=base: retreat is SDK base -X')
        self.tactile_retreat_speed_mm_s = float(self.get_parameter('tactile_retreat_speed_mm_s').value)
        if not math.isfinite(self.tactile_retreat_speed_mm_s) or self.tactile_retreat_speed_mm_s <= 0:
            raise ValueError('tactile_retreat_speed_mm_s must be finite and positive')
        self.calib_mode = str(self.get_parameter('calib_mode').value).lower()
        self.tool_xyzabc = [float(v) for v in self.get_parameter('tool_xyzabc').value]
        # 工作空间包络: 相对启动时 TCP 位置的球形限位 (mm), 0=禁用
        self.envelope_radius_mm = float(self.get_parameter('envelope_radius_mm').value)
        self.start_mode = int(self.get_parameter('start_mode').value)
        self.imp_k = [float(v) for v in self.get_parameter('imp_k').value]
        self.imp_d = [float(v) for v in self.get_parameter('imp_d').value]
        self.root_frame = str(self.get_parameter('root_frame').value)
        self.arm_base_frame = str(self.get_parameter('arm_base_frame').value)
        if self.start_mode not in (STATE_POSITION, STATE_TORQUE):
            raise ValueError(
                f"start_mode 参数必须是 1 (位置跟随) 或 3 (关节阻抗), got {self.start_mode}")
        if len(self.imp_k) != 7 or len(self.imp_d) != 7:
            raise ValueError('imp_k / imp_d 必须是 7 元素列表')

        for name, value in [('ctrl_rate', self.ctrl_rate),
                            ('delta_timeout', self.delta_timeout),
                            ('policy_command_rate', self.policy_command_rate),
                            ('manual_command_rate', self.manual_command_rate),
                            ('manual_timeout', self.manual_timeout),
                            ('max_step_deg', self.max_step_deg)]:
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be positive and finite')
        if not math.isfinite(self.envelope_radius_mm) or self.envelope_radius_mm < 0:
            raise ValueError('envelope_radius_mm must be nonnegative and finite')
        if len(self.tool_xyzabc) != 6 or not all(math.isfinite(v) for v in self.tool_xyzabc):
            raise ValueError('tool_xyzabc must have six finite values')
        if not all(math.isfinite(v) for v in self.imp_k + self.imp_d):
            raise ValueError('imp_k and imp_d must be finite')
        if self.delta_frame not in ('tcp', 'base'):
            raise ValueError(f"delta_frame 参数必须是 'tcp' 或 'base', got '{self.delta_frame}'")
        if self.calib_mode not in ('identity', 'measure'):
            raise ValueError(f"calib_mode 参数必须是 'identity' 或 'measure', got '{self.calib_mode}'")
        if self.delta_splits < 1:
            raise ValueError(f'delta_splits 必须 >= 1, got {self.delta_splits}')
        self.frame = FRAME_TCP if self.delta_frame == 'tcp' else FRAME_BASE

        if self.arm not in ('A', 'B'):
            raise ValueError(f"arm 参数必须是 'A' 或 'B', got '{self.arm}'")
        self.arm_idx = 0 if self.arm == 'A' else 1
        # 臂基 TF frame 名: 与控制器 /tf 树的命名一致 (Base_L / Base_R)
        if not self.arm_base_frame:
            self.arm_base_frame = 'Base_L' if self.arm == 'A' else 'Base_R'

        # ---------- 共享状态 (须在 _connect_robot 之前创建, _set_mode 会用到) ----------
        self.lock = threading.Lock()
        self.traj_queue = []            # 200Hz 待执行子增量队列 (每项: 平移 mm, 旋转 deg)
        self.have_goal = False
        self.queue_is_retreat = False
        self.manual_velocity = [0.0] * 6  # mm/s, deg/s; 手柄话题专用
        self.policy_velocity = [0.0] * 6
        self.last_policy_time = time.monotonic()
        self.last_manual_time = time.monotonic()
        self.queue_source = 'policy'
        self.guard_generation = 0
        self.pending_guard_hold = False
        self.last_delta_time = self.get_clock().now()
        self.cmd_fb_err_strikes = 0
        # 启动锚点: TCP 位置包络以连接时的位形为基准
        self.tcp_anchor = None
        # 当前目标关节角 (度): 连接成功后会被 _connect_robot / _set_mode
        # 重置为机械臂真实反馈, 这里只是未连接 (connect_on_start:=false) 时的占位
        self.cur_joints = [0.0] * 7

        # ---------- 机械臂 SDK ----------
        self.robot = None
        self.dcss = None
        self.kine = None
        if self.connect_on_start:
            try:
                self._connect_robot()
            except Exception:
                if self.robot is not None:
                    try:
                        self.robot.release_robot()
                    except Exception as cleanup_error:
                        self.get_logger().error(f'release_robot after startup failure: {cleanup_error}')
                    finally:
                        self.robot = None
                raise

        # ---------- ROS I/O ----------
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,   # 只保留最新一条增量, 旧增量直接丢弃
        )
        self.hil_pending = None
        self.hil_receipt_pub = self.create_publisher(String, '/omi/action/receipt', 10)
        self.sub = self.create_subscription(
            Float64MultiArray, self.delta_topic, self.hil_delta_callback, qos)
        self.manual_sub = self.create_subscription(
            Float64MultiArray, self.manual_delta_topic, self.manual_delta_callback, qos)

        self.home_srv = self.create_service(
            Trigger, '/delta_ctrl_node/home_poses', self.home_poses_callback)
        if self.tactile_guard.enabled:
            self.tactile_subs = [self.create_subscription(
                WrenchStamped, '/omi/tactile_grid24x16/' + side + '/wrench',
                lambda msg, side=side: self.tactile_callback(side, msg),
                QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
                for side in ('a', 'b')]
            self.guard_baseline_srv = self.create_service(
                Trigger, '/delta_ctrl_node/capture_tactile_baseline', self.guard_baseline_callback)
            self.guard_reset_srv = self.create_service(
                Trigger, '/delta_ctrl_node/reset_tactile_guard', self.guard_reset_callback)
            self.guard_pub = self.create_publisher(String, '/omi/safety/tactile_guard', 1)
            self.guard_timer = self.create_timer(0.1, self.publish_guard_status)

        if self.pub_js:
            self.js_pub = self.create_publisher(Jointfeedback, '/tj/info/joint_feedback', 10)
            self.js_timer = self.create_timer(0.02, self.publish_joint_state)  # 50Hz

        # 左臂末端工具位姿 (基坐标系, xyz 单位 m, 姿态四元数)
        self.eef_rate = float(self.get_parameter('eef_publish_rate').value)
        if self.eef_rate > 0:
            # base_link -> 臂基安装变换 (URDF J1 原点), 程序内直接复合,
            # 不经 TF 回环 (见 _root_mount_matrix)
            self.root_mount = self._root_mount_matrix()
            # 静态 TF 仅供 RViz 等外部显示; eef_left 复合不依赖它
            self.tf_buffer = tf2_ros.Buffer()
            self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)
            self._publish_root_mount_tf()
            self.eef_pub = self.create_publisher(PoseStamped, '/tj/info/eef_left', 10)
            self.eef_timer = self.create_timer(
                1.0 / self.eef_rate, self.publish_eef_pose)
            self.get_logger().info(
                f'eef_left 发布启用: {self.root_frame} <- {self.arm_base_frame} '
                f'(SDK TCP FK @臂基系 -> 固定安装变换复合)')

        # 200Hz 控制定时器
        self.ctrl_timer = self.create_timer(
            1.0 / self.ctrl_rate, self.ctrl_loop,
            clock=Clock(clock_type=ClockType.STEADY_TIME))

        self.get_logger().info(
            f'delta_ctrl_node 启动: arm={self.arm}, ip={self.robot_ip}, '
            f'rate={self.ctrl_rate}Hz, topic={self.delta_topic}, '
            f'manual_topic={self.manual_delta_topic}, '
            f'manual_command_rate={self.manual_command_rate}Hz, '
            f'manual_timeout={self.manual_timeout}s, '
            f'policy_command_rate={self.policy_command_rate}Hz, policy_timeout={self.delta_timeout}s')

    # ---------------- Receiver-owned tactile protection ----------------
    def _check_tactile_guard(self):
        """Called with self.lock held; watchdog also runs without new actions."""
        state = self.tactile_guard.evaluate(time.monotonic())
        new_trip = self.guard_generation != self.tactile_guard.generation
        policy_queue = self.queue_source == 'policy'
        blocked_queue = (policy_queue and self.have_goal and state not in ('clear', 'disabled') and
                         not (state == 'latched' and self.queue_is_retreat))
        self.guard_generation = self.tactile_guard.generation
        if (new_trip and policy_queue and self.have_goal) or blocked_queue:
            self.guard_generation = self.tactile_guard.generation
            self.traj_queue = []
            self.have_goal = False
            self.queue_is_retreat = False
            self.policy_velocity = [0.0] * 6
            self.pending_guard_hold = self.robot is not None
            self.hil_finish('tactile_guard', accepted=False)
            self.get_logger().warn('Tactile guard: ' + self.tactile_guard.reason)
        return state

    def tactile_callback(self, side, msg):
        w = msg.wrench
        values = [w.force.x, w.force.y, w.force.z, w.torque.x, w.torque.y, w.torque.z]
        with self.lock:
            self.tactile_guard.update(side, values, time.monotonic())
            self._check_tactile_guard()

    def guard_baseline_callback(self, request, response):
        with self.lock:
            if self.have_goal or self.pending_guard_hold:
                response.success, response.message = False, 'stop motion before baseline capture'
            else:
                response.success, response.message = self.tactile_guard.capture_baseline(time.monotonic())
                self.guard_generation = self.tactile_guard.generation
        return response

    def guard_reset_callback(self, request, response):
        with self.lock:
            if self.have_goal or self.pending_guard_hold:
                response.success, response.message = False, 'stop retreat/hold before reset'
            else:
                response.success, response.message = self.tactile_guard.reset(time.monotonic())
                self.guard_generation = self.tactile_guard.generation
        return response

    def publish_guard_status(self):
        with self.lock:
            self._check_tactile_guard()
            status = self.tactile_guard.status(time.monotonic())
            status['pending_feedback_hold'] = self.pending_guard_hold
            status['retreat_speed_mm_s'] = self.tactile_retreat_speed_mm_s
            status['scope'] = 'policy_only'
            status['queue_source'] = self.queue_source
        self.guard_pub.publish(String(data=json.dumps(status)))

    def _apply_guard_hold(self):
        """Replace the previous SDK target with current feedback, not just silence.

        This is a position-reference hold, NOT a certified stop/unloading command.
        Failed feedback/SDK calls keep the gate closed and are retried.
        """
        try:
            sub = self.robot.subscribe(self.dcss)
            joints = [float(v) for v in sub['outputs'][self.arm_idx]['fb_joint_pos']]
            if len(joints) != 7 or not all(math.isfinite(v) for v in joints):
                raise ValueError('invalid feedback for tactile hold')
            self.robot.clear_set()
            if not self.robot.set_joint_cmd_pose(arm=self.arm, joints=joints):
                raise RuntimeError('feedback hold command rejected')
            self.robot.send_cmd()
        except Exception as exc:
            self.get_logger().error('Tactile hold failed: ' + str(exc), throttle_duration_sec=1.0)
            return
        with self.lock:
            self.cur_joints = joints
            self.cmd_fb_err_strikes = 0
            self.pending_guard_hold = False

    # ---------------- 机械臂连接 ----------------
    def _connect_robot(self):
        if not self.motion_authorized:
            raise RuntimeError('Robot startup requires explicit motion authorization')
        sdk_dir = os.environ.get('ARM_SDK_DIR')
        if not sdk_dir:
            raise RuntimeError('Set ARM_SDK_DIR to the archived OpticalModule_PU/Arm_control')
        if not os.path.isfile(os.path.join(sdk_dir, 'ccs_m6_40.MvKDCfg')):
            raise RuntimeError(f'Missing SDK configuration in {sdk_dir}')
        if sdk_dir not in sys.path:
            sys.path.insert(0, sdk_dir)
        from fx_kine import Marvin_Kine
        from fx_robot import Marvin_Robot, DCSS
        from fx_tcp_force import TcpForceKine
        config_path = os.path.join(sdk_dir, 'ccs_m6_40.MvKDCfg')
        # 用完整版 Marvin_Robot (OnLinkTo 链路): 它提供 clear_set/send_cmd/
        # set_state/set_joint_cmd_pose 等指令接口; Concise_Marvin_Robot 是精简
        # 规划接口版, 没有这些方法。与实机验证过的 verify_tcp_force_impedance.py 同类
        self.robot = Marvin_Robot()
        if self.robot.connect(robot_ip=self.robot_ip) == 0:
            self.get_logger().error(f'连接机械臂失败: {self.robot_ip}')
            raise RuntimeError('robot connect failed')
        time.sleep(0.2)
        self.robot.log_switch('0')       # 关控制器日志, 减少干扰 (联调期可改 '1')
        self.robot.local_log_switch('0')
        self.dcss = DCSS()
        self.robot.check_error_and_clear(self.dcss)
        # 等 UDP 数据通道刷新 (frame_serial 变化) 再读反馈, 否则可能拿到零值/旧值,
        # 导致标定和 IK 参考全错 (与 verify_tcp_force_impedance.py 同款保护)
        motion_tag, frame_update = 0, None
        for _ in range(50):
            sub = self.robot.subscribe(self.dcss)
            if sub is None:
                time.sleep(0.01)
                continue
            fs = sub['outputs'][self.arm_idx]['frame_serial']
            if fs != 0 and fs != frame_update:
                motion_tag += 1
                frame_update = fs
            time.sleep(0.01)
        if motion_tag == 0:
            raise RuntimeError('UDP 数据通道未刷新, 连接失败')
        sub = self.robot.subscribe(self.dcss)
        fb = sub['outputs'][self.arm_idx]['fb_joint_pos']
        self.cur_joints = list(fb)
        self.get_logger().info(f'机械臂当前关节角: {[round(j, 2) for j in fb]}')

        self.kine = Marvin_Kine()
        ini = self.kine.load_config(arm_type=self.arm_idx, config_path=config_path)
        if ini is None:
            raise RuntimeError('load_config failed')
        self.kine.initial_kine(
            robot_type=ini['TYPE'][self.arm_idx],
            dh=ini['DH'][self.arm_idx],
            pnva=ini['PNVA'][self.arm_idx],
            j67=ini['BD'][self.arm_idx])

        # ---------- TCP 标定 (运动前, 移植 FX_Robot_Kine_CalibrateTcpTool) ----------
        # 计算侧先清 Tool/UserFrame 保证 FK 结果就是法兰位姿 B_T_F (控制器侧 Tool 未动)
        self.tk = TcpForceKine(self.kine)
        if not self.tk.remove_tool_and_user_frame():
            raise RuntimeError('remove_tool_and_user_frame failed')
        # identity 标定: B_T_TCP = B_T_F, 即 TCP 与法兰重合;
        # measure 模式: 用手量工具尺寸构造 B_T_TCP = B_T_F × F_T_TCP 后标定
        b_t_f = self.kine.fk(self.cur_joints)
        if not b_t_f:
            raise RuntimeError('标定前 FK 失败, 无法获取法兰位姿')
        if self.calib_mode == 'measure':
            f_t_tcp = self.kine.xyzabc_to_mat4x4(self.tool_xyzabc)
            if not f_t_tcp:
                raise RuntimeError(f'tool_xyzabc 无效: {self.tool_xyzabc}')
            b_t_tcp = [[sum(b_t_f[r][k] * f_t_tcp[k][c] for k in range(4))
                        for c in range(4)] for r in range(4)]
        else:
            b_t_tcp = b_t_f
        ok, tool = self.tk.calibrate_tcp_tool(b_t_f, b_t_tcp)
        if not ok:
            raise RuntimeError('calibrate_tcp_tool 标定失败')
        self.get_logger().info(
            f'TCP 标定成功 (mode={self.calib_mode}), F_T_TCP =\n'
            + '\n'.join('  [' + ', '.join(f'{v:9.3f}' for v in row) + ']' for row in tool))

        # 记录启动时 TCP 位置锚点 (工作空间包络基准)
        if self.envelope_radius_mm > 0:
            tcp0 = self.kine.fk(self.cur_joints)
            if tcp0:
                self.tcp_anchor = [tcp0[r][3] for r in range(3)]
                self.get_logger().info(
                    f'工作空间包络启用: TCP 锚点 {[round(v, 1) for v in self.tcp_anchor]} mm, '
                    f'半径 {self.envelope_radius_mm} mm')

        # 进入启动模式 (默认位置跟随)。注意: 必须用 clear_set + set_state +
        # set_vel_acc + send_cmd 显式切状态, set_position_state (SetJointMode)
        # 只设速度/加速度百分比不切状态, 会导致机械臂向控制器内部零位指令运动
        if not self._set_mode(self.start_mode):
            raise RuntimeError(f'进入启动模式 {self.start_mode} 失败')
        self.get_logger().info(
            f'机械臂连接成功, 当前模式: {self._mode_name(self.start_mode)}')

    # ---------------- 模式控制 ----------------
    @staticmethod
    def _mode_name(state: int) -> str:
        return {STATE_POSITION: '位置跟随',
                STATE_TORQUE: '关节阻抗'}.get(state, f'未知({state})')

    def _set_mode(self, state: int) -> bool:
        """切换机械臂控制模式。state=1 位置跟随; state=3 关节阻抗。

        返回 True 表示已确认进入目标模式。切换前先清空增量队列,
        避免旧模式的指令流串到新模式。
        """
        if self.robot is None or self.dcss is None:
            self.get_logger().error('未连接机械臂, 无法切换模式')
            return False

        with self.lock:
            self.traj_queue = []
            self.have_goal = False

        if state == STATE_POSITION:
            # 位置跟随: 直接切状态
            self.robot.clear_set()
            ok1 = self.robot.set_state(arm=self.arm, state=state)
            ok2 = self.robot.set_vel_acc(arm=self.arm, velRatio=30, AccRatio=30)
            self.robot.send_cmd()
            wait = 0.8
        elif state == STATE_TORQUE:
            # 关节阻抗: 先设低刚度 K/D, 再切扭矩状态 + imp_type=1
            # (与 verify_tcp_force_impedance.py 实测序列一致)
            self.robot.clear_set()
            self.robot.set_joint_kd_params(arm=self.arm, K=self.imp_k, D=self.imp_d)
            self.robot.set_vel_acc(arm=self.arm, velRatio=10, AccRatio=10)
            self.robot.send_cmd()
            time.sleep(0.5)
            self.robot.clear_set()
            ok1 = self.robot.set_state(arm=self.arm, state=state)
            ok2 = self.robot.set_impedance_type(arm=self.arm, type=1)
            self.robot.send_cmd()
            wait = 1.0
        else:
            self.get_logger().error(f'不支持的模式 {state}, 仅支持 1 (位置跟随) / 3 (关节阻抗)')
            return False

        if not ok1:
            self.get_logger().error(f'set_state({state}) 失败')
            return False
        if ok2 is False:
            self.get_logger().error('模式参数设置失败')
            return False
        time.sleep(wait)  # 预留状态切换时间

        # 回读确认
        sub = self.robot.subscribe(self.dcss)
        if sub is None:
            self.get_logger().error('切换模式后订阅失败, 无法确认状态')
            return False
        st = sub['states'][self.arm_idx]
        if st['cur_state'] != state:
            self.get_logger().error(
                f'未能进入 {self._mode_name(state)} (cur_state={st["cur_state"]}, '
                f'cmd_state={st["cmd_state"]}, err={st["err_code"]})')
            return False

        # 模式切换后以当前反馈为新的指令迭代起点, 防止从旧起点跳变
        self.cur_joints = list(sub['outputs'][self.arm_idx]['fb_joint_pos'])
        self.cmd_fb_err_strikes = 0
        self.get_logger().info(f'已切换到 {self._mode_name(state)} (state={state})')
        return True

    def hil_finish(self, status, *, accepted):
        """Report terminal command outcome; SDK delivery is not measured completion."""
        pending, self.hil_pending = getattr(self, 'hil_pending', None), None
        if pending:
            self.hil_receipt_pub.publish(String(data=json.dumps(dict(pending, status=status,
                accepted=accepted, finished=True, velocity_hold_continues=(status == 'velocity_window_sent'),
                timestamp_ns=self.get_clock().now().nanoseconds))))

    def hil_delta_callback(self, msg, *, manual=False):
        """Optional tagged HIL receipt: queue acceptance, not measured execution."""
        dims = msg.layout.dim
        command_id = dims[0].label if dims and dims[0].label.startswith('hil:') else None
        result = None
        if getattr(self, 'hil_pending', None):
            self.hil_finish('queue_cancelled' if not command_id and not any(msg.data) else 'queue_replaced',
                            accepted=not command_id and not any(msg.data))
        try:
            if not command_id or (self.delta_frame == 'base' and self.arm == 'A'):
                result = self._delta_callback(msg, manual=True) if manual else self.delta_callback(msg)
        finally:
            if command_id:
                receipt = dict(command_id=command_id, accepted=bool(result and result['accepted']),
                               status='queue_accepted' if result and result['accepted'] else 'rejected_or_modified',
                               wire_action=list(msg.data), delta_frame=self.delta_frame, arm=self.arm,
                               timestamp_ns=self.get_clock().now().nanoseconds,
                               execution_confirmed=False, finished=not bool(result and result["accepted"]),
                               control_mode='velocity_hold',
                               action_source='human' if manual else 'policy',
                               nominal_duration_s=1.0 / (self.manual_command_rate if manual else self.policy_command_rate),
                               velocity_hold_continues=bool(result and result['accepted'] and self.have_goal))
                if receipt["accepted"] and not self.have_goal:
                    receipt.update(status="velocity_zero_stopped", finished=True)
                elif receipt["accepted"]:
                    self.hil_pending = receipt
                self.hil_receipt_pub.publish(String(data=json.dumps(receipt)))

    # ---------------- 增量回调 (10Hz) ----------------
    def delta_callback(self, msg: Float64MultiArray):
        return self._delta_callback(msg, manual=False)

    def manual_delta_callback(self, msg: Float64MultiArray):
        dims = msg.layout.dim
        if dims and dims[0].label.startswith('hil:'):
            return self.hil_delta_callback(msg, manual=True)
        if (getattr(self, 'hil_pending', None) and self.hil_pending.get('action_source') == 'human'
                and len(msg.data) == 6 and not any(msg.data)):
            self.hil_finish('queue_cancelled', accepted=True)
        self.hil_finish("external_manual_takeover", accepted=False)
        return self._delta_callback(msg, manual=True)

    def _delta_callback(self, msg: Float64MultiArray, *, manual):
        if msg.data is None or len(msg.data) != 6:
            if manual:
                with self.lock:
                    self._stop_manual_motion()
            else:
                with self.lock:
                    self._stop_policy_motion()
            self.get_logger().warn('增量数据长度应为 6', throttle_duration_sec=1.0)
            return

        if not all(math.isfinite(float(v)) for v in msg.data):
            if manual:
                with self.lock:
                    self._stop_manual_motion()
            else:
                with self.lock:
                    self._stop_policy_motion()
            self.get_logger().warn('拒绝非有限增量')
            return

        if self.kine is None or self.robot is None:
            self.get_logger().warn('未连接机械臂 (connect_on_start:=false), 丢弃增量',
                                   throttle_duration_sec=5.0)
            return

        with self.lock:
            if manual:
                velocity = [float(v) * self.manual_command_rate for v in msg.data]
                if not all(math.isfinite(v) for v in velocity):
                    self._stop_manual_motion()
                    self.get_logger().warn('拒绝非有限手柄速度')
                    return
                # Trusted human input replaces policy motion and any pending policy hold.
                self.traj_queue = []
                self.queue_source = 'manual'
                self.queue_is_retreat = False
                self.pending_guard_hold = False
                self.policy_velocity = [0.0] * 6
                self.manual_velocity = velocity
                self.last_manual_time = time.monotonic()
                self.have_goal = any(velocity)
                self._check_tactile_guard()
                # An explicit zero (RB release/disconnect/handoff) stops immediately.
                return dict(accepted=True)
            else:
                self._check_tactile_guard()
                action, reason = self.tactile_guard.filter_action(msg.data, time.monotonic())
            if action is None or self.pending_guard_hold:
                if self.queue_source == 'manual':
                    # A blocked model command must not interrupt human control.
                    return
                # A rejected command must never leave a previous retreat running.
                had_goal = self.have_goal
                self.traj_queue = []
                self.have_goal = False
                self.queue_is_retreat = False
                if had_goal:
                    self.pending_guard_hold = True
                self.get_logger().warn('Tactile action blocked: ' + reason, throttle_duration_sec=1.0)
                return
            hil_modified = list(action) != list(msg.data)
            if hil_modified and any(d.label.startswith('hil:') for d in msg.layout.dim):
                self._stop_policy_motion()
                return None
            velocity = [float(v) * self.policy_command_rate for v in action]
            if reason == 'retreat_only':
                velocity[0] = max(velocity[0], -self.tactile_retreat_speed_mm_s)
            if not all(math.isfinite(v) for v in velocity):
                self._stop_policy_motion()
                self.get_logger().warn('拒绝非有限策略速度')
                return None
            self.manual_velocity = [0.0] * 6
            self.policy_velocity = velocity
            self.last_policy_time = time.monotonic()
            self.last_delta_time = self.get_clock().now()
            self.traj_queue = []
            self.have_goal = any(velocity)
            self.queue_is_retreat = reason == 'retreat_only'
            self.queue_source = 'policy'
            return dict(accepted=not hil_modified)

    def _stop_policy_motion(self):
        """Called with self.lock held; never cancel a trusted manual command."""
        if self.queue_source == 'policy':
            self.policy_velocity = [0.0] * 6
            self.traj_queue = []
            self.have_goal = False
            self.queue_is_retreat = False
            self.hil_finish('invalid_policy_input', accepted=False)

    def _stop_manual_motion(self):
        """Called with self.lock held; invalid manual input must not retain speed."""
        if self.queue_source == 'manual':
            self.manual_velocity = [0.0] * 6
            self.policy_velocity = [0.0] * 6
            self.traj_queue = []
            self.have_goal = False
            self.queue_is_retreat = False

    # ---------------- 200Hz 控制循环 ----------------
    def ctrl_loop(self):
        if self.robot is None:
            return

        with self.lock:
            self._check_tactile_guard()
            needs_hold = self.pending_guard_hold
        if needs_hold:
            self._apply_guard_hold()
            return

        with self.lock:
            manual = self.queue_source == 'manual'
            if not self.have_goal:
                return

            # 两个输入通道均采用单调时钟断流监护。
            since = time.monotonic() - (self.last_manual_time if manual else self.last_policy_time)
            timeout = self.manual_timeout if manual else self.delta_timeout
            if since >= timeout:
                self.hil_finish('receiver_timeout', accepted=False)
                self.traj_queue = []
                self.have_goal = False
                self.manual_velocity = [0.0] * 6
                self.policy_velocity = [0.0] * 6
                self.get_logger().warn(
                    f'控制输入超时 {since:.2f}s >= {timeout}s, 停止下发指令',
                    throttle_duration_sec=5.0)
                return

            # 每周期只计算一个子增量, 本点下发后才会计算下一点。
            if manual:
                # Fixed nominal dt: scheduler delays never produce enlarged catch-up steps.
                sub_t = [v / self.ctrl_rate for v in self.manual_velocity[:3]]
                sub_r = [v / self.ctrl_rate for v in self.manual_velocity[3:]]
            else:
                sub_t = [v / self.ctrl_rate for v in self.policy_velocity[:3]]
                sub_r = [v / self.ctrl_rate for v in self.policy_velocity[3:]]
            q_ref = list(self.cur_joints)
            ok, cmd, tgt_mat = self.tk.solve_tcp_delta_ik(
                q_ref, list(sub_t), list(sub_r), self.frame)
            if not ok:
                self.hil_finish('ik_failed', accepted=False)
                self.traj_queue = []
                self.have_goal = False
                self.manual_velocity = [0.0] * 6
                self.policy_velocity = [0.0] * 6
                self.queue_is_retreat = False
                self.get_logger().warn(
                    '子增量 IK 失败, 停止剩余增量'
                    + (f', 诊断目标矩阵: {tgt_mat}' if tgt_mat else ''),
                    throttle_duration_sec=1.0)
                return

            # 每步相对最近已下发指令限幅。
            for j in range(7):
                d = cmd[j] - q_ref[j]
                if abs(d) > self.max_step_deg:
                    if getattr(self, 'hil_pending', None):
                        self.hil_finish('joint_clamp', accepted=False)
                        self.traj_queue = []
                        self.have_goal = False
                        self.manual_velocity = [0.0] * 6
                        self.policy_velocity = [0.0] * 6
                        return
                    cmd[j] = q_ref[j] + math.copysign(self.max_step_deg, d)

            # 每个点位下发前检查包络, 超界点及后续子增量都不下发。
            if self.tcp_anchor is not None:
                t_end = self.kine.fk(cmd)
                if t_end:
                    p = [t_end[r][3] for r in range(3)]
                    dist = math.sqrt(sum(
                        (p[i] - self.tcp_anchor[i]) ** 2 for i in range(3)))
                    if dist > self.envelope_radius_mm:
                        self.hil_finish('envelope_rejected', accepted=False)
                        self.traj_queue = []
                        self.have_goal = False
                        self.manual_velocity = [0.0] * 6
                        self.policy_velocity = [0.0] * 6
                        self.queue_is_retreat = False
                        self.get_logger().warn(
                            f'TCP 目标距启动锚点 {dist:.1f} mm 超出包络 '
                            f'{self.envelope_radius_mm} mm, 停止剩余增量',
                            throttle_duration_sec=1.0)
                        return

            fb = None
            if self.dcss is not None:
                sub = self.robot.subscribe(self.dcss)
                if sub is not None:
                    fb = sub['outputs'][self.arm_idx]['fb_joint_pos']

        # SDK 调用放锁外, 避免阻塞回调线程。
        # 与实机验证过的 verify_tcp_force_impedance.py 完全同款三件套:
        # clear_set → set_joint_cmd_pose (关节跟踪指令) → send_cmd。
        # 缺 clear_set/send_cmd 包裹时指令可能不生效 (2025-03 实测症状:
        # IK 在跑、指令在发, 机械臂不动, 指令-反馈偏差持续增大)
        self.robot.clear_set()
        if not self.robot.set_joint_cmd_pose(arm=self.arm, joints=[float(v) for v in cmd]):
            self.hil_finish('sdk_rejected', accepted=False)
            self.get_logger().error('set_joint_cmd_pose 失败', throttle_duration_sec=1.0)
            with self.lock:
                self.traj_queue = []
                self.have_goal = False
                self.manual_velocity = [0.0] * 6
                self.policy_velocity = [0.0] * 6
                self.queue_is_retreat = False
            return
        self.robot.send_cmd()

        stop = False
        with self.lock:
            self.cur_joints = cmd  # 下一条增量的 FK/IK 从本指令值继续

            # 指令-反馈偏差监护: 任一关节指令与反馈偏差过大且持续, 立即停发。
            # 防止标定/IK 参考错误时机械臂被带向错误位形
            if fb is not None and len(fb) == 7:
                err = max(abs(c - f) for c, f in zip(cmd, fb))
                if err > MAX_CMD_FB_ERR_DEG:
                    self.cmd_fb_err_strikes += 1
                    if self.cmd_fb_err_strikes >= CMD_FB_ERR_STRIKES:
                        self.get_logger().error(
                            f'指令-反馈偏差 {err:.1f}° > {MAX_CMD_FB_ERR_DEG}° '
                            f'连续 {self.cmd_fb_err_strikes} 次, 停止下发指令! '
                            '请检查 arm 参数 (A/B) 与急停')
                        self.traj_queue = []
                        self.have_goal = False
                        self.manual_velocity = [0.0] * 6
                        self.policy_velocity = [0.0] * 6
                        stop = True
                else:
                    self.cmd_fb_err_strikes = 0
        # 停发后不再调用 SDK (锁外执行, 此处只是跳过后续周期下发)
        if stop:
            self.hil_finish('feedback_error', accepted=False)
            return
        if getattr(self, 'hil_pending', None):
            last_time = self.last_manual_time if manual else self.last_policy_time
            rate = self.manual_command_rate if manual else self.policy_command_rate
            if time.monotonic() - last_time >= 1.0 / rate:
                self.hil_finish('velocity_window_sent', accepted=True)

    # ---------------- 关节状态发布 ----------------
    def publish_joint_state(self):
        if self.robot is None or self.dcss is None:
            return
        sub = self.robot.subscribe(self.dcss)
        if sub is None:
            return
        out = sub['outputs'][self.arm_idx]
        # marvin_msgs/Jointfeedback: 固定 14 维 (L1~L7, R1~R7),
        # 本节点只控制一条臂, 另一条臂的 7 维填 0。
        # SDK 反馈角度/角速度单位为度, 这里转换为弧度发布
        msg = Jointfeedback()
        msg.header.stamp = self.get_clock().now().to_msg()
        pos = [0.0] * 14
        vel = [0.0] * 14
        eff = [0.0] * 14
        base = 0 if self.arm == 'A' else 7
        pos[base:base + 7] = [math.radians(float(v)) for v in out['fb_joint_pos']]
        vel[base:base + 7] = [math.radians(float(v)) for v in out['fb_joint_vel']]
        eff[base:base + 7] = [float(v) for v in out['fb_joint_sToq']]
        msg.positions = pos
        msg.velocities = vel
        msg.efforts = eff
        self.js_pub.publish(msg)

    @staticmethod
    def _mat_to_quat(m):
        """4x4 位姿矩阵的旋转部分 -> 四元数 (x, y, z, w)。"""
        tr = m[0][0] + m[1][1] + m[2][2]
        if tr > 0:
            s = math.sqrt(tr + 1.0) * 2
            w = 0.25 * s
            x = (m[2][1] - m[1][2]) / s
            y = (m[0][2] - m[2][0]) / s
            z = (m[1][0] - m[0][1]) / s
        elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
            s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
            w = (m[2][1] - m[1][2]) / s
            x = 0.25 * s
            y = (m[0][1] + m[1][0]) / s
            z = (m[0][2] + m[2][0]) / s
        elif m[1][1] > m[2][2]:
            s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
            w = (m[0][2] - m[2][0]) / s
            x = (m[0][1] + m[1][0]) / s
            y = 0.25 * s
            z = (m[1][2] + m[2][1]) / s
        else:
            s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
            w = (m[1][0] - m[0][1]) / s
            x = (m[0][2] + m[2][0]) / s
            y = (m[1][2] + m[2][1]) / s
            z = 0.25 * s
        return x, y, z, w

    def _publish_root_mount_tf(self):
        """发布 base_link -> 臂基的静态安装 TF（左臂 Y 为修正值）。

        URDF 根连杆 ZJ_Robot_link 即 base_link, J1 安装原点给出根坐标系到臂基:
          Arm_L1_Joint: xyz(0, 0.0260, 1.121) rpy(-90°, 0, 0)   (arm=A, Y 修正值)
          Arm_R1_Joint: xyz(0, -0.2005, 1.121) rpy(+90°, 0, 0)  (arm=B)
        rpy(-90°,0,0) 的四元数为 (x=-√2/2, w=√2/2), (+90°,0,0) 取反号。
        publish_root_tf='none' 时不发布 (由外部 static_transform_publisher 提供)。
        """
        if str(self.get_parameter('publish_root_tf').value).lower() != 'urdf':
            return
        if self.arm == 'A':
            x, y, z = 0.0, 0.0260, 1.121
            qx, qw = -math.sqrt(2.0) / 2.0, math.sqrt(2.0) / 2.0
        else:
            x, y, z = 0.0, -0.2005, 1.121
            qx, qw = math.sqrt(2.0) / 2.0, math.sqrt(2.0) / 2.0
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = self.root_frame
        t.child_frame_id = self.arm_base_frame
        t.transform.translation.x = x
        t.transform.translation.y = y
        t.transform.translation.z = z
        t.transform.rotation.x = qx
        t.transform.rotation.w = qw
        self.tf_static_broadcaster = tf2_ros.StaticTransformBroadcaster(self)
        self.tf_static_broadcaster.sendTransform(t)
        self.get_logger().info(
            f'静态安装 TF 已发布: {self.root_frame} -> {self.arm_base_frame} '
            f'xyz=({x}, {y}, {z}) rpy=(±90°, 0, 0) (左臂 Y 为修正值)')

    def _root_mount_matrix(self):
        """base_link -> 臂基的固定安装变换 (4x4, m)。
        旋转及高度基于 Stand URDF J1；左臂 Y 为修正值。根连杆 ZJ_Robot_link 即 base_link:
          Arm_L1_Joint: xyz(0, 0.0260, 1.121) rpy(-90°, 0, 0)   (arm=A, Y 修正值)
          Arm_R1_Joint: xyz(0, -0.2005, 1.121) rpy(+90°, 0, 0)
        URDF 手臂 4 关节等连杆系定义不采用, 仅用此根安装变换; 臂内正运动学
        一律以 SDK FK 为准。
        """
        if self.arm == 'A':
            return [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0260],
                [0.0, -1.0, 0.0, 1.121],
                [0.0, 0.0, 0.0, 1.0],
            ]
        return [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, -1.0, -0.2005],
            [0.0, 1.0, 0.0, 1.121],
            [0.0, 0.0, 0.0, 1.0],
        ]

    def _transform_to_root(self, pose):
        """把臂基坐标系下的 SDK TCP 位姿矩阵变换到 base_link (机器人根坐标系)。

        位姿按 root_mount × pose 复合 (root_mount = URDF J1 安装变换,
        base_link -> 臂基, 程序内固定值, 不查 TF)。FK 平移为 mm, 输出转 m。
        返回 (位姿矩阵[平移 m], frame_id)。
        """
        m = self.root_mount
        # FK 平移是 mm, 先转 m 再复合
        p = [pose[i][3] / 1000.0 for i in range(3)]
        out = [[0.0] * 4 for _ in range(4)]
        for r_i in range(3):
            for c in range(3):
                out[r_i][c] = sum(m[r_i][k] * pose[k][c] for k in range(3))
            out[r_i][3] = (m[r_i][0] * p[0] + m[r_i][1] * p[1]
                           + m[r_i][2] * p[2]) + m[r_i][3]
        out[3][3] = 1.0
        return out, self.root_frame

    def home_poses_callback(self, request, response):
        """Read-only current/target TCP FK, sharing eef_left's calibrated kine.

        Return SDK BASE matrices in meters; BASE increments avoid root mounting
        offsets and gamepad installation presets. SDK joint inputs use degrees.
        """
        try:
            if self.arm != 'A' or self.robot is None or self.kine is None or self.dcss is None:
                raise ValueError('需要已连接的左臂 A')
            if self.delta_frame != 'base':
                raise ValueError('返回需要 BASE 话题控制模式')
            sub = self.robot.subscribe(self.dcss)
            if sub is None:
                raise ValueError('无法读取当前关节反馈')
            joints = sub['outputs'][self.arm_idx]['fb_joint_pos']
            home_rad = [1.36784420538524, -1.3972774378908723,
                        -0.8460047216729514, -1.4080845166192213,
                        -0.26412765702130986, -0.1478974554847475,
                        0.6224018645536978]
            current = self.kine.fk([float(v) for v in joints])
            target = self.kine.fk([math.degrees(v) for v in home_rad])
            if current is None or target is None:
                raise ValueError('FK 失败')
            poses = []
            for matrix in (current, target):
                pose = [[float(matrix[r][c]) for c in range(4)] for r in range(4)]
                if not all(math.isfinite(v) for row in pose for v in row):
                    raise ValueError('FK 返回非有限值')
                for r in range(3):
                    pose[r][3] /= 1000.
                poses.append(pose)
            if self.tcp_anchor is not None:
                distance = math.sqrt(sum((poses[1][r][3]*1000-self.tcp_anchor[r])**2
                                         for r in range(3)))
                if distance > self.envelope_radius_mm:
                    raise ValueError(f'目标距启动锚点 {distance:.1f} mm，超出包络 '
                                     f'{self.envelope_radius_mm:.1f} mm')
            response.message = json.dumps(dict(frame='sdk_base', current=poses[0], target=poses[1]))
            response.success = True
        except Exception as exc:
            response.success = False
            response.message = str(exc)
        return response

    def publish_eef_pose(self):
        """发布左臂末端工具位姿 /tj/info/eef_left (geometry_msgs/PoseStamped)。

        FK 自当前反馈关节角得到 TCP 位姿 (臂基坐标系, mm/度矩阵), 再
        通过程序内固定安装矩阵转换到机器人根坐标系,
        位置 xyz 为米, 姿态旋转矩阵转换为四元数 (x, y, z, w)。
        """
        if self.robot is None or self.dcss is None or self.kine is None:
            return
        sub = self.robot.subscribe(self.dcss)
        if sub is None:
            return
        joints = sub['outputs'][self.arm_idx]['fb_joint_pos']
        pose = self.kine.fk([float(v) for v in joints])
        if not pose:
            return
        pose, frame_id = self._transform_to_root(pose)
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = frame_id
        msg.pose.position.x = pose[0][3]
        msg.pose.position.y = pose[1][3]
        msg.pose.position.z = pose[2][3]
        qx, qy, qz, qw = self._mat_to_quat(pose)
        msg.pose.orientation.x = qx
        msg.pose.orientation.y = qy
        msg.pose.orientation.z = qz
        msg.pose.orientation.w = qw
        self.eef_pub.publish(msg)

    def shutdown(self):
        if self.robot is not None:
            try:
                self.robot.release_robot()
            except Exception as e:
                self.get_logger().error(f'release_robot 异常: {e}')


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = DeltaCtrlNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.shutdown()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
