# 将录制的末端位姿转为增量并回放

独立脚本：`scripts/replay_eef_pose.py`。Python 3.10+、NumPy；prepare/send需要设备对应ROS环境。
不依赖OMI训练环境或torch。可将脚本与生成的数据目录一起复制到Humble机器。

## 数据与动作定义

本次输入 `/home/zhoutong/Downloads/oct04/robot_pose/bag_002`，只有右臂
`/tj/info/eef_right` PoseStamped，31500条，33.836秒，frame_id=`base_link`。
按PoseStamped的SI约定将位置解释为米，姿态为xyzw四元数；设备实际单位仍须保持该约定。
用户确认本次用右臂验证，以后迁移左臂。

固定10Hz，对位置线性插值、四元数最短弧SLERP。相邻采样位姿形成动作：

```
dp = p_next - p_current
 dr = Log(R_next R_current^T)
wire = [1000*dp, 180/pi*dr]  # mm、度，基座系旋转向量
R_target = Exp(dr) R_current
```

这是当前OMI六维末端动作的数学定义，复用其语义，不将右臂数据冒充左臂训练数据。
发送端仿照axis_test.py：`/omi/action_test/decision`、Float64MultiArray、空layout。
不是欧拉角、不是速度，也不是将0.1秒增量重复发送20次。
**控制端旋转解释仍沿用用户此前指定的基座系旋转向量假设，未检查接收端。**

从实测位姿生成的是运动结果增量，不是原操作者的控制命令。
离线重建正确不保证真机轨迹一致，尤其接收端按实时反馈而非上一目标积分时。
脚本采用预先计算的开环增量序列，不根据跟踪误差自动补偿，以便测量原始跟踪结果。

## 已导出的数据

| 目录（项目内） | 范围与速度 | 命令数/时长 | 最大单步平移/旋转 |
|---|---|---|---|
| `local/eef_replay/oct04_right_bag002` | 全程原速 | 339 / 33.9s | 35.17mm / 4.194° |
| `local/eef_replay/oct04_right_bag002_probe_s005` | 原记录11–13s、0.05倍速 | 400 / 40s | 0.8804mm / 0.0812° |

用户明确要求整段测试：默认使用第一行全程原速数据，包含前约11秒静止和全部后续运动。第二行仅为可选短片段；不代替全程测试。减速延长时间，不缩小轨迹空间范围。
片段总位移约 `[+1.922,-36.382,+3.762] mm`，不是总共只动0.88mm。
通用发送器默认1mm/0.2°会拒绝原速整段；整段入口显式采用36mm/4.3°作为数据幅度检查，覆盖源轨迹最大值。这是对当前数据的检查范围，不是已验证的设备安全限幅。
目录中另外的`first5s_slow`是近静止样例，`motion_probe`是0.1倍速试算（最大1.224mm），不是推荐首测。

每个数据目录含manifest.json、trajectory.npz与actions.csv。
manifest保存起点、终点、重建误差、重采样误差和NPZ哈希。
原速10Hz采样点重建误差为浮点精度；插值轨迹对原始高频位置最大差8.664mm、姿态1.033°。
0.05倍速短片段相应为0.4475mm、0.03675°。高频记录含重复位置及离散更新，不能把插值当新增测量。

重新导出（输出必须为新目录）：

```bash
python3 scripts/replay_eef_pose.py prepare /path/to/bag_002 \
  --speed 1 --rate 10 \
  --output local/eef_replay/my_full
```

默认header时间，发现非递增、空/变化frame、非法四元数或>50ms数据缺口会拒绝。
末尾不足一个周期时，在最后完整周期到达源记录终点，最多延长一个周期。
离线导出使用未来采样点进行插值，适用于已知轨迹回放，不是在线策略的因果观测构造。

## 在右臂控制机器发送

先启用与axis_test.py相同的控制接收端和右臂反馈发布端，并使用相同ROS_DOMAIN_ID。
**不要同时运行原bag播放器、axis_test.py或其他动作发布者。** bag播放器可能把历史位姿伪装成在线反馈。
反馈时间戳需与本机ROS时钟一致。脚本不会自动寻址机器人、启用驱动或移动到起点。

将右臂手动放至完整记录起点，位置约 `[480.480,-143.085,858.574] mm`，
xyzw四元数约 `[-0.00639710,0.02363122,0.02212123,0.99945550]`。
仅位置一致不够，姿态、基座轴和TCP也必须对应。

在Humble控制机器（此工作站测试环境是Jazzy）：

```bash
source /opt/ros/humble/setup.bash
cd /path/to/omi_proj
bash scripts/replay_right_bag002_full.sh
```

`--confirm-controller-contract`表示操作者确认选臂、坐标/TCP、米制反馈、mm/度增量和旋转约定；
不是软件自动验证接收端。随后回车开始检查，收集2秒新反馈，起点误差默认不得超过2mm/1°。
通用发送器默认1mm/0.2°，整段入口显式设置36mm/4.3°（范数，数据检查而非设备保证）；不会静默裁剪或跳过动作。整段339条，名义33.9秒，另有启动反馈检查2秒和末尾等待1秒。
重复执行请用`--log local/eef_replay/right_full_run2.jsonl`指定新日志，禁止覆盖旧证据。
反馈不新鲜、执行调度迟到>20ms、命令订阅者数量不等于1会停止发布，不追赶积压命令。
停止发布不等于控制柜停止：异常时使用设备已经验证的停止手段，脚本不擅自失能。

## 比较结果

发送时保存实际下发命令、本机接收时间、反馈header时间、完整反馈位姿和完成/中止状态。
结束或中止时自动生成`.comparison.json`与`.comparison.csv`，也可重算：

```bash
python3 scripts/replay_eef_pose.py compare \
  local/eef_replay/oct04_right_bag002 \
  local/eef_replay/right_full_run1.jsonl
```

指标包括按名义时间对齐的绝对位置/姿态RMSE、最大误差、覆盖区间、实际下发条数、
完成状态，以及完整运行后等待1秒的终点误差。CSV可画实际和参考轨迹。
默认不做最佳时间平移、刚体配准或起点偏移消除，因此不会掩盖滞后或起点误差。
本机反馈接收时间包含传输延迟；时序误差不全是空间路径误差。中止的局部结果不能当全程验收。
`complete`只表示发送流程和最终反馈检查完成，不表示机器人轨迹通过某个精度门槛。

迁移左臂时重新从左臂bag prepare，指定`--pose-topic /tj/info/eef_left`，并确认接收端选臂、
基座与TCP定义。不能直接把右臂绝对起点用到左臂。

## 本机验证边界

5项离线测试通过，含非交换旋转、四元数符号、SLERP、与现有OMI动作实现的一致性、比较器与数据匹配检查。
隔离localhost domain177、专用`/omi/replay_mock/decision`模拟接收10/10条，空layout、
mm/度单位、命令顺序、积分终点检查通过。证据在`local/eef_replay/mock_ros/`。
未向真实`/omi/action_test/decision`发送，未连接设备，Humble和真机轨迹一致性待现场验证。
