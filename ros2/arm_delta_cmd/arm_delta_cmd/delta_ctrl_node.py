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
  4. 控制源切换: 服务 /delta_ctrl_node/set_keyboard_control (std_srvs/SetBool)
     - data=true: 切到键盘控制 (不改变机械臂模式, pynput 监听按键,
       按住方向键 200Hz 增量移动, 空格退出并切回话题控制)
     - data=false: 切回话题控制
     键盘控制键位 (沿 TCP 自身轴): q/w=±X  a/s=±Y  z/e=±Z
     r/f=±Rx  t/g=±Ry  y/h=±Rz
  4. 每收到一条增量: 若上一条增量的队列还没走完, 直接丢弃旧队列剩余部分,
     以最新指令为起点重新解算本条增量 (增量控制始终采用最新数据);
     然后把这条增量按时间均分为
     N=20 个子增量, 逐个子增量调用 TcpForceKine.solve_tcp_delta_ik()
     (移植自 FX_Robot_Kine_SolveTcpDeltaIK) 做精确的 TCP/BASE 系增量 IK,
     得到 N 个目标关节角组成队列
  5. 200Hz 定时器: 每周期从队列取出下一个目标关节角, 通过 SDK
     set_joint_cmd_pose (关节跟踪指令, 位置跟随与关节阻抗模式均有效) 下发。
     N=20 步恰好用 20 个 200Hz 周期 (0.1s) 走完, 与 10Hz 增量节奏对齐
     (关节阻抗模式下指令是阻抗控制的参考位置, 手推仍可柔顺偏离)

依赖: Arm_control SDK，由 ARM_SDK_DIR 指定；仅授权连接时导入。
来源及迁移差异见 tutorials/robot_controller.md；原始副本保存在 local/vendor。
"""

import math
import os
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Float64MultiArray
from std_srvs.srv import SetBool
from marvin_msgs.msg import Jointfeedback
from geometry_msgs.msg import PoseStamped
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

# 控制源枚举
CTRL_SOURCE_TOPIC = 'topic'
CTRL_SOURCE_KEYBOARD = 'keyboard'

# 键盘控制参数 (与 verify_tcp_force_impedance.py 一致)
KEY_STEP_MM = 0.1       # 每控制周期平移增量 mm
KEY_STEP_DEG = 0.1      # 每控制周期旋转增量 deg
# 键位 -> (平移方向, 旋转方向) (TCP 系)
KEY_MOVES = {
    'q': ([+1, 0, 0], [0, 0, 0]), 'w': ([-1, 0, 0], [0, 0, 0]),
    'a': ([0, +1, 0], [0, 0, 0]), 's': ([0, -1, 0], [0, 0, 0]),
    'z': ([0, 0, +1], [0, 0, 0]), 'e': ([0, 0, -1], [0, 0, 0]),
    'r': ([0, 0, 0], [+1, 0, 0]), 'f': ([0, 0, 0], [-1, 0, 0]),
    't': ([0, 0, 0], [0, +1, 0]), 'g': ([0, 0, 0], [0, -1, 0]),
    'y': ([0, 0, 0], [0, 0, +1]), 'h': ([0, 0, 0], [0, 0, -1]),
}


class KeyState:
    """pynput 后台线程维护的按键按下集合 (小写字符键 + 空格)。

    read() 返回 (按下键集合, 自上次调用以来是否有状态变化)。
    """

    def __init__(self, log=None):
        import pynput
        self._pressed = set()
        self._changed = False
        self._lock = threading.Lock()
        self._listener = pynput.keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._log = log
        try:
            self._listener.start()
        except Exception as e:
            self._listener = None
            if self._log is not None:
                self._log(f'pynput 监听启动失败 (键盘控制不可用): {e}')

    def _norm(self, key):
        try:
            ch = key.char
            return ch.lower() if ch else None
        except AttributeError:
            return None  # 特殊键 (Shift 等) 不参与控制

    def _on_press(self, key):
        ch = self._norm(key)
        if ch is None:
            return
        with self._lock:
            if ch not in self._pressed:
                self._pressed.add(ch)
                self._changed = True

    def _on_release(self, key):
        ch = self._norm(key)
        if ch is None:
            return
        with self._lock:
            if ch in self._pressed:
                self._pressed.discard(ch)
                self._changed = True

    def read(self):
        with self._lock:
            pressed = set(self._pressed)
            changed = self._changed
            self._changed = False
        return pressed, changed

    @property
    def ok(self):
        return self._listener is not None

    def close(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


class DeltaCtrlNode(Node):
    def __init__(self):
        super().__init__('delta_ctrl_node')

        # ---------- 参数 ----------
        self.declare_parameter('robot_ip', '192.168.14.190')
        self.declare_parameter('arm', 'A')              # A / B
        self.declare_parameter('delta_topic', '/omi/action/decision')
        self.declare_parameter('ctrl_rate', 200.0)      # Hz
        self.declare_parameter('delta_timeout', 0.5)    # s, 超时无增量则停止发送
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
        #   'urdf'   = 按 Marvin_Stand_2026.2.2 URDF J1 安装原点发布静态 TF
        #              (左: xyz(0, 0.2005, 1.121) rpy(-90°,0,0);
        #               右: xyz(0, -0.2005, 1.121) rpy(+90°,0,0))
        #   'none'   = 不发布, 依赖外部节点提供 root_frame -> arm_base_frame
        self.declare_parameter('publish_root_tf', 'urdf')

        self.robot_ip = self.get_parameter('robot_ip').value
        self.arm = self.get_parameter('arm').value
        self.delta_topic = self.get_parameter('delta_topic').value
        self.ctrl_rate = float(self.get_parameter('ctrl_rate').value)
        self.delta_timeout = float(self.get_parameter('delta_timeout').value)
        self.max_step_deg = float(self.get_parameter('max_step_deg').value)
        self.delta_splits = int(self.get_parameter('delta_splits').value)
        self.pub_js = bool(self.get_parameter('enable_publish_joint_state').value)
        self.connect_on_start = bool(self.get_parameter('connect_on_start').value)
        self.motion_authorized = bool(self.get_parameter('motion_authorized').value)
        if self.connect_on_start and not self.motion_authorized:
            raise ValueError('connect_on_start requires motion_authorized=true: startup changes robot mode')
        self.delta_frame = str(self.get_parameter('delta_frame').value).lower()
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
        self.traj_queue = []            # 200Hz 待下发目标关节角队列 (每项 7 关节)
        self.have_goal = False
        self.last_delta_time = self.get_clock().now()
        self.cmd_fb_err_strikes = 0
        # 启动锚点: TCP 位置包络以连接时的位形为基准
        self.tcp_anchor = None
        # 当前目标关节角 (度): 连接成功后会被 _connect_robot / _set_mode
        # 重置为机械臂真实反馈, 这里只是未连接 (connect_on_start:=false) 时的占位
        self.cur_joints = [0.0] * 7

        # ---------- 控制源状态 ----------
        self.control_source = CTRL_SOURCE_TOPIC
        self.keys = None                # KeyState, 进入键盘控制时创建

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
        self.sub = self.create_subscription(
            Float64MultiArray, self.delta_topic, self.delta_callback, qos)

        # 控制源切换: std_srvs/SetBool, true=键盘控制, false=话题控制
        self.kb_srv = self.create_service(
            SetBool, '/delta_ctrl_node/set_keyboard_control', self.keyboard_control_callback)

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
                f'(SDK TCP FK @臂基系 -> URDF J1 安装变换复合)')

        # 200Hz 控制定时器
        self.ctrl_timer = self.create_timer(1.0 / self.ctrl_rate, self.ctrl_loop)

        self.get_logger().info(
            f'delta_ctrl_node 启动: arm={self.arm}, ip={self.robot_ip}, '
            f'rate={self.ctrl_rate}Hz, topic={self.delta_topic}')

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

    # ---------------- 控制源切换 ----------------
    def keyboard_control_callback(self, request, response):
        """std_srvs/SetBool: true=切到键盘控制, false=切回话题控制。"""
        want_kb = bool(request.data)
        with self.lock:
            current = self.control_source
        if want_kb and current == CTRL_SOURCE_KEYBOARD:
            response.success = True
            response.message = 'already in keyboard control'
            return response
        if not want_kb and current == CTRL_SOURCE_TOPIC:
            response.success = True
            response.message = 'already in topic control'
            return response

        if want_kb:
            if not self._enter_keyboard():
                response.success = False
                response.message = 'enter keyboard control failed'
            else:
                response.success = True
                response.message = 'keyboard control enabled'
        else:
            self._exit_keyboard()
            response.success = True
            response.message = 'topic control enabled'
        return response

    def _enter_keyboard(self) -> bool:
        """进入键盘控制: 清空增量队列, 启动 pynput 监听。

        不改变机械臂控制模式: 位置跟随模式下键盘增量走位置指令;
        关节阻抗模式下指令是阻抗参考位置 (手推仍可柔顺偏离)。
        """
        if self.robot is None:
            self.get_logger().error('未连接机械臂, 无法进入键盘控制')
            return False

        with self.lock:
            self.traj_queue = []
            self.have_goal = False
            self.control_source = CTRL_SOURCE_KEYBOARD

        if self.keys is None:
            self.keys = KeyState(log=self.get_logger().error)
            if not self.keys.ok:
                self._exit_keyboard_internal()
                return False

        self.get_logger().info(
            '已进入键盘控制 (保持当前机械臂模式)。键位 (沿 TCP 自身轴, 按住才动): '
            'q/w=±X  a/s=±Y  z/e=±Z  r/f=±Rx  t/g=±Ry  y/h=±Rz, 空格=退出')

        # 以当前反馈为键盘移动的 IK 迭代起点
        sub = self.robot.subscribe(self.dcss)
        if sub is not None:
            with self.lock:
                self.cur_joints = list(
                    sub['outputs'][self.arm_idx]['fb_joint_pos'])
        return True

    def _exit_keyboard(self):
        """退出键盘控制, 切回话题控制 (机械臂模式保持不变)。"""
        self._exit_keyboard_internal()
        self.get_logger().info('已退出键盘控制, 切回话题控制')

    def _exit_keyboard_internal(self):
        with self.lock:
            self.traj_queue = []
            self.have_goal = False
            self.control_source = CTRL_SOURCE_TOPIC
        if self.keys is not None:
            self.keys.close()
            self.keys = None

    # ---------------- 键盘控制 (200Hz 定时器内) ----------------
    def keyboard_ctrl(self):
        """键盘控制的增量移动: 读按键 -> 合成各方向键增量 -> TCP 系增量 IK
        -> 安全检查 -> 下发。

        按住方向键才动 (每键 KEY_STEP_MM/KEY_STEP_DEG 每周期), 松开即停。
        多键同按时把各键增量矢量相加 (如 q+z = ±X±Z 同时移动), 合成一条
        增量做一次 IK。空格退出并切回话题控制。
        复用 delta_callback 同款保护: 包络检查由增量 IK + max_step_deg 限幅 +
        envelope_radius_mm 包络承担 (键盘单周期 0.1mm/0.1° 远小于限幅, 安全)。
        """
        pressed, _ = self.keys.read()

        if ' ' in pressed:
            self.get_logger().info('键盘控制: 空格, 退出键盘控制')
            self._exit_keyboard()
            return

        dir_keys = pressed & set(KEY_MOVES)
        if not dir_keys:
            return

        # 合成所有按下方向键的增量矢量 (TCP 系)
        delta_t = [0.0, 0.0, 0.0]
        delta_r = [0.0, 0.0, 0.0]
        for key in sorted(dir_keys):
            d_t, d_r = KEY_MOVES[key]
            for i in range(3):
                delta_t[i] += d_t[i] * KEY_STEP_MM
                delta_r[i] += d_r[i] * KEY_STEP_DEG

        with self.lock:
            q_ref = list(self.cur_joints)

        # 增量 IK (TCP 系; cur_joints 是最近指令, 比反馈更平滑)
        ok, q_target, _ = self.tk.solve_tcp_delta_ik(
            q_ref, delta_t, delta_r, FRAME_TCP)
        if not ok:
            self.get_logger().warn(
                f'键盘控制: {"".join(sorted(dir_keys))} 组合 IK 失败, 停止',
                throttle_duration_sec=1.0)
            return

        # 安全限幅 (与 delta_callback 同款)
        for j in range(7):
            d = q_target[j] - q_ref[j]
            if abs(d) > self.max_step_deg:
                q_target[j] = q_ref[j] + math.copysign(self.max_step_deg, d)

        # 工作空间包络检查 (与 delta_callback 同款)
        if self.tcp_anchor is not None:
            t_end = self.kine.fk(q_target)
            if t_end:
                p = [t_end[r][3] for r in range(3)]
                dist = math.sqrt(sum(
                    (p[i] - self.tcp_anchor[i]) ** 2 for i in range(3)))
                if dist > self.envelope_radius_mm:
                    self.get_logger().warn(
                        f'键盘控制: TCP 目标距锚点 {dist:.1f} mm 超出包络 '
                        f'{self.envelope_radius_mm} mm, 拒绝该方向',
                        throttle_duration_sec=1.0)
                    return

        # SDK 三件套 (clear_set → set_joint_cmd_pose → send_cmd), 锁外执行
        self.robot.clear_set()
        if not self.robot.set_joint_cmd_pose(
                arm=self.arm, joints=[float(v) for v in q_target]):
            self.get_logger().error('set_joint_cmd_pose 失败', throttle_duration_sec=1.0)
            return
        self.robot.send_cmd()

        with self.lock:
            self.cur_joints = q_target  # 下个周期从本指令值继续
            self.cmd_fb_err_strikes = 0

    # ---------------- 增量回调 (10Hz) ----------------
    def delta_callback(self, msg: Float64MultiArray):
        if msg.data is None or len(msg.data) != 6:
            self.get_logger().warn('增量数据长度应为 6', throttle_duration_sec=1.0)
            return

        if not all(math.isfinite(float(v)) for v in msg.data):
            self.get_logger().warn('拒绝非有限增量')
            return

        if self.kine is None or self.robot is None:
            self.get_logger().warn('未连接机械臂 (connect_on_start:=false), 丢弃增量',
                                   throttle_duration_sec=5.0)
            return

        # 键盘控制期间忽略话题增量
        with self.lock:
            if self.control_source != CTRL_SOURCE_TOPIC:
                self.get_logger().warn(
                    '当前为键盘控制, 忽略话题增量 (调用 '
                    '/delta_ctrl_node/set_keyboard_control data:=false 切回话题控制)',
                    throttle_duration_sec=5.0)
                return

        dx, dy, dz, drx, dry, drz = [float(v) for v in msg.data]

        with self.lock:
            # 上一条增量的队列还没走完: 丢弃旧队列剩余部分, 用本条新增量
            # 重新解算 (增量控制以最新数据为准, 不堆积旧增量)
            if self.have_goal:
                self.get_logger().info('上条增量队列未走完, 丢弃旧队列, 采用本条新增量',
                                       throttle_duration_sec=1.0)

            # 收到新增量, 刷新超时计时基准 (ctrl_loop 以此判断上游断流)
            self.last_delta_time = self.get_clock().now()

            n = self.delta_splits
            # 1. 均分: 把整条增量切成 n 个子增量, 每个子增量位移/旋转均为整条的 1/n
            sub_t = [dx / n, dy / n, dz / n]
            sub_r = [drx / n, dry / n, drz / n]

            # 2. 逐个子增量做 IK (移植 FX_Robot_Kine_SolveTcpDeltaIK):
            #    每次都从上一步的结果关节角出发, FK -> 按 frame (TCP/BASE) 精确
            #    合成目标位姿 -> IK (参考当前关节角, NEAR_REF 防解跳变),
            #    n 个目标关节角依次入队
            queue = []
            q_ref = list(self.cur_joints)
            for i in range(n):
                ok, q_i, tgt_mat = self.tk.solve_tcp_delta_ik(
                    q_ref, sub_t, sub_r, self.frame)
                if not ok:
                    # 失败语义三档: q_i=None 时不可用; tgt_mat 保留仅供诊断。
                    # 整条增量作废, 队列一条都不下发, 机械臂保持在原地
                    self.get_logger().warn(
                        f'子增量 {i + 1}/{n} IK 失败 (不可达/超限/输入无效), '
                        '整条增量作废'
                        + (f', 诊断目标矩阵: {tgt_mat}' if tgt_mat else ''),
                        throttle_duration_sec=1.0)
                    return

                # 安全限幅: 每步目标相对上一步限幅, 防异常增量导致机械臂突跳
                base = queue[-1] if queue else self.cur_joints
                for j in range(7):
                    d = q_i[j] - base[j]
                    if abs(d) > self.max_step_deg:
                        q_i[j] = base[j] + math.copysign(self.max_step_deg, d)
                queue.append(q_i)
                q_ref = q_i  # 下一个子增量从本步目标出发

            # 3. 整条增量全部解算成功, 才切换到新队列
            # 工作空间包络检查: 队列末端 TCP 相对启动锚点超界则整条作废
            if self.tcp_anchor is not None:
                t_end = self.kine.fk(queue[-1])
                if t_end:
                    p = [t_end[r][3] for r in range(3)]
                    dist = math.sqrt(sum((p[i] - self.tcp_anchor[i]) ** 2 for i in range(3)))
                    if dist > self.envelope_radius_mm:
                        self.get_logger().warn(
                            f'TCP 目标距启动锚点 {dist:.1f} mm 超出包络 '
                            f'{self.envelope_radius_mm} mm, 整条增量作废',
                            throttle_duration_sec=1.0)
                        return

            self.traj_queue = queue
            self.have_goal = True

            self.get_logger().debug(
                f'增量 [{dx:.2f},{dy:.2f},{dz:.2f},{drx:.3f},{dry:.3f},{drz:.3f}] '
                f'({self.delta_frame} 系) -> 切分 {n} 步, 末端目标关节 '
                f'{[round(j, 2) for j in queue[-1]]}')

    # ---------------- 200Hz 控制循环 ----------------
    def ctrl_loop(self):
        if self.robot is None:
            return

        # 键盘控制分支 (200Hz 增量移动; 话题队列逻辑不参与)
        with self.lock:
            kb = self.control_source == CTRL_SOURCE_KEYBOARD
        if kb:
            if self.keys is not None and self.keys.ok:
                self.keyboard_ctrl()
            return

        with self.lock:
            if not self.have_goal or not self.traj_queue:
                return

            # 增量超时: 清空队列停在原地不再下发
            since = (self.get_clock().now() - self.last_delta_time).nanoseconds * 1e-9
            if since > self.delta_timeout:
                self.traj_queue = []
                self.have_goal = False
                self.get_logger().warn(
                    f'增量超时 {since:.2f}s > {self.delta_timeout}s, 停止下发指令',
                    throttle_duration_sec=5.0)
                return

            # 每周期弹出下一个目标, 200Hz 逐点下发 (20 步 = 0.1s, 对齐 10Hz)
            cmd = self.traj_queue.pop(0)
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
            self.get_logger().error('set_joint_cmd_pose 失败', throttle_duration_sec=1.0)
        self.robot.send_cmd()

        stop = False
        with self.lock:
            self.cur_joints = cmd  # 下一条增量的 FK/IK 从本指令值继续
            if not self.traj_queue:
                self.have_goal = False  # 队列走完, 允许接收下一条增量

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
                        stop = True
                else:
                    self.cmd_fb_err_strikes = 0
        # 停发后不再调用 SDK (锁外执行, 此处只是跳过后续周期下发)
        if stop:
            return

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
        """按 Marvin_Stand_2026.2.2 URDF 发布 base_link -> 臂基 的静态安装 TF。

        URDF 根连杆 ZJ_Robot_link 即 base_link, J1 安装原点给出根坐标系到臂基:
          Arm_L1_Joint: xyz(0, 0.2005, 1.121) rpy(-90°, 0, 0)   (arm=A)
          Arm_R1_Joint: xyz(0, -0.2005, 1.121) rpy(+90°, 0, 0)  (arm=B)
        rpy(-90°,0,0) 的四元数为 (x=-√2/2, w=√2/2), (+90°,0,0) 取反号。
        publish_root_tf='none' 时不发布 (由外部 static_transform_publisher 提供)。
        """
        if str(self.get_parameter('publish_root_tf').value).lower() != 'urdf':
            return
        if self.arm == 'A':
            x, y, z = 0.0, 0.2005, 1.121
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
            f'xyz=({x}, {y}, {z}) rpy=(±90°, 0, 0) (来源: Marvin_Stand_2026.2.2 URDF J1)')

    def _root_mount_matrix(self):
        """base_link -> 臂基 的固定安装变换 (4x4, m), 取自 Marvin_Stand_2026.2.2
        URDF 的 J1 安装原点 (URDF 根连杆 ZJ_Robot_link 即 base_link):
          Arm_L1_Joint: xyz(0, 0.2005, 1.121) rpy(-90°, 0, 0)   (arm=A)
          Arm_R1_Joint: xyz(0, -0.2005, 1.121) rpy(+90°, 0, 0)
        URDF 手臂 4 关节等连杆系定义不采用, 仅用此根安装变换; 臂内正运动学
        一律以 SDK FK 为准。
        """
        if self.arm == 'A':
            return [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.2005],
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

    def publish_eef_pose(self):
        """发布左臂末端工具位姿 /tj/info/eef_left (geometry_msgs/PoseStamped)。

        FK 自当前反馈关节角得到 TCP 位姿 (臂基坐标系, mm/度矩阵), 再通过
        /tf 中 root_frame -> arm_base_frame 的变换转换到机器人根坐标系,
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
        self._exit_keyboard_internal()   # 停 pynput 监听 (若在跑)
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
