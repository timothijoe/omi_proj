# 在其他电脑复现手柄末端控制：Agent 执行手册

## 0. 目标与版本

本手册复现**手柄直接控制末端**：Linux 手柄 → 六维增量 → 可选安装坐标/SDK角度转换 → ROS 2 topic。
不需要训练模型、相机、触觉、URDF、bag、CUDA或策略服务；也不启动RL训练。

可复现代码基线：Git提交 **`96e92e7`**（`feat: add gamepad teleoperation and SDK frame conversion`）。
不要仅依赖分支名或当前工作区：它们可能包含后续未提交的策略联调工作。
入口固定为 `scripts/gamepad_test.py`；本手册不用 `gamepad_node --publish` 或 `run_policy_gamepad.sh`。
接收端原有机械臂控制程序需要单独准备，本文件不包含厂商控制器的实现。

已验证发送环境：Ubuntu 24.04、ROS 2 Jazzy、Python 3.12、Linux `/dev/input/js0` Xbox 360兼容手柄。
其他ROS发行版、操作系统或手柄型号不在已验证范围。发送端程序使用Linux ioctl，不能直接在Windows/macOS运行。

## 1. 获取代码：完整仓库或最小包二选一

### A. 已有仓库访问权限

在新电脑取得仓库，并在独立目录或worktree中检出 `96e92e7`，不要重置已有脏工作区。
例如在已有仓库内执行：

```bash
git worktree add --detach ../omi-gamepad-repro 96e92e7
cd ../omi-gamepad-repro
```

原仓库远端地址不在本文中假设；由仓库持有人提供。该提交此前只做本地commit，没有push，远端不一定有它。

### B. 无仓库权限：由原电脑导出最小文件包

在拥有上述提交的原仓库根目录执行：

```bash
git archive --format=tar.gz -o /tmp/omi-gamepad-96e92e7.tar.gz 96e92e7 \
  scripts/gamepad_test.py \
  src/omi_hil_rl/__init__.py \
  src/omi_hil_rl/real/__init__.py \
  src/omi_hil_rl/real/observation.py \
  src/omi_hil_rl/real/gamepad_control.py \
  src/omi_hil_rl/real/linux_gamepad.py \
  src/omi_hil_rl/real/sdk_action.py
sha256sum /tmp/omi-gamepad-96e92e7.tar.gz
```

将压缩包及**本手册**一起传到新电脑，并比对压缩包SHA256。
本手册是在基线提交之后新增的，不包含在上述git archive中，需要单独复制。
在新电脑解压到任意新目录，例如：

```bash
mkdir -p ~/omi-gamepad-repro
tar -xzf /path/to/omi-gamepad-96e92e7.tar.gz -C ~/omi-gamepad-repro
cd ~/omi-gamepad-repro
```

将 `/path/to/` 替换成收到压缩包的目录。保留 scripts 与 src 的相对布局，不要只复制单个Python脚本。
`real/__init__.py` 会导入 observation.py，所以这个看似无关的文件也必须保留。
最小包不包含依赖、ROS、SDK、机器人接收程序或后续policy联调文件。

## 2. 准备发送电脑环境

以下命令假设目标机已经安装匹配Ubuntu版本的 **ROS 2 Jazzy**，存在 `/opt/ros/jazzy/setup.bash`。
如果没有，先按该电脑实际系统安装ROS；不要在其他发行版的机器上盲目使用Jazzy路径。
新环境推荐使用系统Python创建独立venv，以兼容系统安装的rclpy二进制。

在解压目录或worktree根目录执行：

```bash
sudo apt-get install python3-venv ros-jazzy-rclpy ros-jazzy-std-msgs
/usr/bin/python3 -m venv --system-site-packages .venv-gamepad
source /opt/ros/jazzy/setup.bash
source .venv-gamepad/bin/activate
python3 -m pip install 'numpy>=2,<3' 'gymnasium>=1,<2'
python3 -c 'import sys, numpy, gymnasium, rclpy; from std_msgs.msg import Float64MultiArray; print(sys.executable); print("imports OK")'
python3 scripts/gamepad_test.py --help
```

包版本范围来自项目声明；不是精确依赖锁定。保存实际版本，便于追踪：

```bash
python3 -m pip freeze > gamepad-environment.txt
```

不必安装整个项目，也不要为此安装MuJoCo/PyTorch。gymnasium来自包初始化的间接依赖，不能遗漏。
这条最小部署路径不使用原项目的 scripts/env_ros.sh，不依赖原电脑的local目录或marvin_msgs overlay。
若Python版本与ROS二进制不匹配，重建与ROS匹配的venv，不要靠手工复制rclpy到别的Python解决。

每次打开新终端，都要重新进入目录并加载ROS和venv：

```bash
cd ~/omi-gamepad-repro
source /opt/ros/jazzy/setup.bash
source .venv-gamepad/bin/activate
```

## 3. 连接手柄与预览

先检查设备：

```bash
ls -l /dev/input/js*
python3 scripts/gamepad_test.py --device /dev/input/js0 --scale 0.5 \
  --output-convention sdk-x-forward-z-left
```

此时没有 --execute，不创建ROS动作publisher。根据实际设备节点调整 --device。
成功连接但未按RB时显示 idle；按住RB显示human；找不到/无权访问/不支持的设备显示disconnected及错误。
若遇权限不足，按该机器的设备组或ACL配置用户访问权限；不要用sudo运行整个控制程序掩盖问题。
实现要求左/右摇杆、十字键及RB的Linux语义轴/按钮代码；仅有js节点不代表该型号完全兼容。

按住RB逐项检查，不要同时开其他控制程序：

| 操作 | 原始动作方向 |
| --- | --- |
| 右摇杆向前/向后 | +X/-X |
| 右摇杆向左/向右 | +Y/-Y |
| 十字键上/下 | +Z/-Z |
| 左摇杆向右/向左 | +Rx/-Rx |
| 左摇杆向前/向后 | +Ry/-Ry |
| 十字键左/右 | +Rz/-Rz |

默认死区0.15；摇杆按幅度变速，十字键固定速度；平移、旋转分别限制合速度。
RB松开或断连输出零；只按RB但控制回中也是零。本入口不恢复策略、不控制夹爪。

## 4. 理解scale与输出wrapper

默认10Hz、基础平移10mm/s、基础旋转10degree/s。
--scale同时乘这两个速度，**不会启用换轴**。scale=0.5时每步最大平移0.5mm、旋转向量模长0.5°。
单独调速示例：`--speed-mm-s 5 --rotation-deg-s 2 --scale 1`。
--rate改变频率时会相应改变每步增量，不能让接收端再乘一次dt。

| --output-convention | 最终输出 |
| --- | --- |
| legacy（默认） | 原坐标平移mm、旋转向量degree分量，不换轴也不转ABC |
| sdk-base-aligned | 原坐标平移mm、SDK ABC增量degree |
| sdk-x-forward-z-left | 安装换轴后的平移mm、SDK ABC增量degree |

安装预设只是明确假设：操作系+X前/+Y左/+Z上；SDK系+X前/+Z左/+Y下。
平移与旋转向量均用 `(x,y,z) → (x,-z,y)`，等价矩阵 `[[1,0,0],[0,0,-1],[0,1,0]]`。
换轴后的旋转向量还要转换成满足 `ΔR=Rz(C)Ry(B)Rx(A)` 的ABC角。
多轴时不能直接把旋转向量当ABC；左右臂安装方向也不能默认相同。
--signs的六个±1作用在转换前，不要重复补偿安装换轴。

纯单轴推满，scale=0.5、10Hz、SDK安装预设下，应得到：

| 意图 | 原始显示值 | 最终消息 |
| --- | --- | --- |
| 向前 | `[0.5,0,0,0,0,0]` | `[0.5,0,0,0,0,0]` |
| 向左 | `[0,0.5,0,0,0,0]` | `[0,0,0.5,0,0,0]` |
| 向上 | `[0,0,0.5,0,0,0]` | `[0,-0.5,0,0,0,0]` |
| 原始+Rx | `[0,0,0,0.5,0,0]` | `[0,0,0,0.5,0,0]` |
| 原始+Ry | `[0,0,0,0,0.5,0]` | `[0,0,0,0,0,0.5]` |
| 原始+Rz | `[0,0,0,0,0,0.5]` | `[0,0,0,0,-0.5,0]` |

原始显示值已过死区/scale/符号/RB处理，平移mm、旋转向量degree，不是原始摇杆读数。
终端明确显示转换是/否、模式、换轴是/否、转ABC是/否，以及转换后最终值。
预览标记“仅预览”，publish后标记“已发布”，后者不证明控制器实际执行成功。
默认每约0.5秒或状态变化打印一次，topic仍按10Hz；显示精度不改变线上数值。

## 5. 跨电脑先验证ROS消息，暂不驱动机械臂

两台电脑连接可互通的同一局域网；本步骤约定临时domain113、测试话题 `/omi/test/gamepad`。
先确认此domain/话题没有机器人控制接收者。不要在测试时打开真实控制接收程序。
两边在加载各自ROS环境后执行：

```bash
export ROS_DOMAIN_ID=113
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

接收电脑执行：

```bash
ros2 topic echo /omi/test/gamepad std_msgs/msg/Float64MultiArray
```

发送电脑在代码根目录、已激活venv的终端执行：

```bash
python3 scripts/gamepad_test.py --execute --topic /omi/test/gamepad \
  --scale 0.5 --output-convention sdk-x-forward-z-left
```

按回车后，未按RB应收到六个零；按住RB操作，应收到上一节对应数值。
确认layout.dim为空、data_offset为0。另一个同环境终端可用 `ros2 topic hz /omi/test/gamepad` 查看频率。
这只是通信与消息检查；网络发现还取决于防火墙、多播和DDS配置，设置同一domain不保证所有网络都能互通。
若无消息，检查双方domain、网卡、发现范围及现有DDS profile是否限制本机；不要盲目清除工作中的DDS配置。
完成后Ctrl+C退出测试发布和echo。

## 6. 接收端契约与真实机械臂试运行

接收端需订阅 `/omi/action/decision`，类型 Float64MultiArray，空layout：
`[dx,dy,dz,dA,dB,dC]`，每条为SDK Base系的mm/ABC degree增量。
SDK应按照这一语义调用（伪代码，不是接收程序的完整替代品）：

```python
ok, q_target, target = tk.solve_tcp_delta_ik(
    current_joints, list(msg.data[:3]), list(msg.data[3:]), FRAME_BASE  # 0
)
# 仅ok为真才进入原接收程序的关节目标执行路径。
```

确认SDK UserFrame为identity或与目标Base定义一致、关节角为SDK要求的degree、TCP/左右臂正确。
如果调用FRAME_TCP=1，末端姿态会再次旋转输入，固定安装wrapper不能抵消它。
SDK的安装Base方向仍需现场核对；本手册的矩阵是待验证预设，不是通用标定。

确认这些条件后，两边都切到domain13，并重启接收程序以继承环境：

```bash
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

发送电脑执行：

```bash
python3 scripts/gamepad_test.py --execute --topic /omi/action/decision \
  --scale 0.5 --output-convention sdk-x-forward-z-left
```

按回车启动，按住RB逐轴短时试验，先平移再旋转；记录预期/实际方向。松RB检查零增量。
不要同时运行axis/circle、另一个手柄节点或策略动作publisher；发现同话题其他publisher时程序退出。
发送程序没有位姿反馈/工作空间/累计位移限制。断连时零增量不等于硬件急停，接收端必须处理命令断流。

## 7. 常见问题定位

| 现象 | 检查 |
| --- | --- |
| python找不到 | 使用本文python3并激活venv；无需安装python-is-python3 |
| 找不到rclpy | source ROS，确认venv的Python与ROS版本匹配、system-site-packages可用 |
| 找不到gymnasium | real包初始化会间接导入，按第2节安装 |
| 找不到omi_hil_rl或observation | 核对最小7文件、src与scripts相对布局，不要只拿一个脚本 |
| disconnected | 查看同一行错误，核对js设备路径/权限/轴与按钮支持 |
| 转换=否 | 漏了 --output-convention，--scale不是转换开关 |
| 数值相同但转换=是 | 零动作或X轴动作换轴后本来就可能不变，标记表示规则已应用 |
| topic正确但方向不对 | 优先查FRAME_BASE/TCP、UserFrame、安装方向、接收端数据重排，不盲目交换按钮 |
| 改代码没效果 | 退出旧进程后重新启动，确认当前目录和解释器 |
| 显示已发布但机械臂不动 | echo仅证明通信；核对真实控制订阅者、IK返回和执行链路 |

## 8. 复现验收与Agent交付要求

记录操作系统、ROS/Python、手柄型号与js路径、代码版本或压缩包SHA256、pip freeze和运行命令。
分别报告：依赖导入、手柄预览、六轴原始/最终数值、RB释放、跨机echo、机器人实际方向。
未做的检查明确标为未验证，不能把echo成功写成机械臂执行成功。
若更改安装映射，记录原因和每轴证据，保持正确右手旋转关系，避免重复变换。

原开发机器证据：手柄/转换/显示测试67项通过；加看板相关测试后的提交检查73项通过。
最小7文件从96e92e7导出后在临时目录验证了 --help 和左轴转换；使用已有Python环境，**不是新电脑全新安装验收**。
已做过隔离domain113消息格式及退出检查；真实安装方向和换轴后的机械臂运动尚未完成正式验收。

仓库内补充资料：`tutorials/gamepad_control.md` 和 `docs/agent/hardware/evolution/gamepad-control.md`。
后续策略联调是独立工作；本手册固定复现基线的纯手柄入口，不对后来工作区的策略进展作结论。
