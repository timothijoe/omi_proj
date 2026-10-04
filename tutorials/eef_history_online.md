# 历史 policy 在线推理与 wrench 开关

> **实机对接暂定约定：** 用户指定暂按基坐标系旋转向量解释控制接口后三维，尚未经接收端核实。策略输出仍为m/rad，axis_test接口为mm/度；单位换算不能替代基坐标系和TCP变换。具体公式与条件见[动作接口对齐说明](../docs/agent/training/evolution/axis-controller-interface.md)。

在项目根目录执行。需要已配置的 ROS Jazzy、marvin_msgs 和 `.venv` 中的 PyTorch。
入口仅订阅观测、发布策略候选，没有机械臂执行器。

## 1. 用现有历史模型启动

```bash
bash scripts/eef_history_online.sh --help
bash scripts/eef_history_online.sh \
  --checkpoint local/eef_history/oct03_split2/history/best.pt \
  --wrench-enabled 0 0
```

默认本机 domain **97**。输入发布进程也必须在 domain97。
脚本通过 `OMI_HISTORY_DOMAIN_ID` 选择 domain，固定 localhost；跨机器传输不在此脚本的默认范围。
例如本机已有 domain13 输入时可设 `OMI_HISTORY_DOMAIN_ID=13`，仍需核实双方传输配置兼容。
脚本不会启动相机、触觉 SDK 或机器人驱动。Ctrl+C 停止。

必需输入：

- `/camera/camera/color/image_raw`：外部相机 Image。
- `/tj/info/joint_feedback`：marvin_msgs/Jointfeedback。
- `/tj/info/eef_left`：PoseStamped，frame_id=base_link。
- `/omi/tactile_grid24x16/{a,b}/{deformation,shear,depth}`：16×24 小矩阵 Image。
- 可选 `/omi/wrist/color/image_roi`：预裁剪 128×128 Image，是否必需由 checkpoint 决定。

v4 另外订阅 `/omi/tactile_grid24x16/{a,b}/wrench`（WrenchStamped），这些 topic 可以不存在。

## 2. 查看输出和历史状态

在已 source ROS 的另一终端：

```bash
export ROS_DOMAIN_ID=97
export ROS_LOCALHOST_ONLY=1
ros2 topic echo /omi/history_shadow/status
# 或另开终端：
ros2 topic echo /omi/history_shadow/action_delta
```

每 100 ms 尝试一次推理。status 的 `history_mask` 从部分有效逐渐变成十个 true。
缺帧保留空位；当前必需数据缺失时 `valid=false`、`action=null`，不会发送动作。
动作是六维增量 `[dx,dy,dz,rx,ry,rz]`，单位 m/rad，基坐标系；不是速度或欧拉角。
它仍使用未来录制位姿作为训练代理标签，不应直接接现有硬件控制 topic。

新任务、录包循环或重新摆放后清历史：

```bash
ros2 topic pub --once /omi/history_shadow/reset std_msgs/msg/Empty '{}'
```

## 3. wrench 是否生效

例如原始 A/B wrench 都有数值：

| 配置/数据 | wrench_enabled | wrench_mask | 输入数值 |
| --- | --- | --- | --- |
| 全部禁用 | [0,0] | [0,0] | 12 个零 |
| A 可用、B 禁用 | [1,0] | [1,0] | A 六维 + B 六个零 |
| 两指启用，B 丢失/过期 | [1,1] | [1,0] | A 六维 + B 六个零 |
| 两指有效，测得真实零 | [1,1] | [1,1] | 12 个零 |

现有 oct03 模型只支持 `[0,0]`，启用会明确报错。
**必须使用新 v4 数据训练出的权重才能启用 wrench。当前没有这份新权重。**
届时可以启动时传 `--wrench-enabled 1 1`，或调整 ROS 参数：

```bash
ros2 param set /omi_history_policy wrench_enabled '[0, 0]'
```

开关变化会清空历史和源数据，防止旧 wrench 特征继续影响后续预测。

## 4. 转换统一 v4 数据集

输出目录必须不存在。即使 bag 有 wrench，下面的 `0 0` 也会强制禁用：

```bash
bash scripts/eef_bc.sh export /path/to/bag_001.zip local/datasets/my_v4/bag_001 \
  --accept-future-state-proxy --input-profile grid-wrench \
  --wrist-camera optional --wrench-enabled 0 0
```

需要保留 A/B wrench 时改为 `--wrench-enabled 1 1`；缺失或无效的测量仍自动置零。
不同包允许不同 enabled 配置，wrench 数组维度一致。
`samples.npz` 保存动作标签样本，`history_observations.npz` 保存完整有效历史输入。
训练时 `eef_bc_history` 会自动读取两者；不要手工删除历史池或将 v3/v4 混进同一次训练。

wrench_mask 说明数值和时间是否可用，不代表 SDK 力单位、轴向已标定。
更详细的字段和接口见[设计说明](../docs/agent/training/evolution/history-online-policy.md)。
