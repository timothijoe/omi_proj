# 录包 → BC初始策略 → ROS影子推理

历史 `local/bc/` 已完成移动盘迁移并校验，本地原目录已移除，没有软链接。
位置与后续路径使用方式见[迁移清单](machine_transfer_checklist.md#历史实验数据的归档位置)。
读取历史结果需改用归档路径，新训练请另选输出目录；下文 `local/bc/` 是工作目录示例。

所有命令从 `omi_proj/` 根目录执行。本入口不会启动硬件、不会发布实际控制命令。
只用于离线示教拟合与ROS回放推理；输出不可直接接机器人。当前只在Ubuntu24.04/Jazzy验收。

## 1. 准备

- 准备包含外部彩色、双侧deformation/shear/depth/force、14轴关节反馈、左臂目标的完整
  MCAP bag目录或ZIP。腕部相机、夹爪开合和末端位姿不是第一版输入。
- 安装Jazzy、rclpy、标准消息、rosbag2_py及MCAP插件、zstd；匹配采集方的marvin_msgs源码
  需在本机colcon构建。按 `scripts/robot_viewer.env.example` 填写
  `local/robot_state/viewer.env` 中的overlay路径。
- 使用Python3.12环境，安装本项目与BC依赖，例如 `.venv/bin/python -m pip install -e '.[bc]'`。
  ROS依赖来自系统安装，不通过pip安装。已验证主项目环境torch为2.14.1+cpu。
  可用 `OMI_BC_PYTHON` 指向另一个已安装本项目且兼容ROS的解释器。
- 这是独立数据入口，不使用RViz截图、PNG缓存、Daimon SDK或机器人mesh。
  该13.55秒包导出时预留约3GB临时/最终空间；数据、权重放Git忽略的local目录。

先查看帮助，不连接设备：

```bash
bash scripts/bag_bc.sh --help
bash scripts/bag_bc.sh export --help
bash scripts/bag_bc.sh train --help
bash scripts/bag_bc.sh shadow --help
```

## 2. 导出一个episode

```bash
bash scripts/bag_bc.sh export /YOUR_DATA_DISK/record001.zip \
  local/bc/record001_dataset --assume-absolute-radian-targets
```

参数明确接受本次实验假设：目标消息是左臂7轴绝对关节目标、单位弧度。
消息定义只有positions，尚未证明生产者语义及控制器实际执行；未确认前只能影子实验。
不要把该选项当作完成硬件标定或运动许可。

每包作为一个episode；若包内包含多次试验，应先按真实任务边界整理，不能随意按帧划分。
10 Hz参考点取不晚于该时刻且已接收的观测，任一路超过250ms或缺失就跳过。
动作标签取参考时刻100ms后第一条目标，额外等待不能超过50ms。
目标和未来信息只用于标签，不进入观测。

输出包括：

- `samples.npz`：RGB `(N,3,128,128)` uint8；触觉 `(N,10,16,24)` float32；
  state `(N,19)`（7关节+双侧12维wrench）；action `(N,7)`，以及参考、来源、标签时间。
- `manifest.json`：输入指纹、消息计数、丢弃原因、契约、数据校验和、未确认语义说明。
- `observations/`：仅10路观测topic的MCAP，不包含目标/夹爪控制topic。
- `references.json`：回放采样参考与源时间水位/输入哈希，不含动作标签。

触觉每指5通道为deformation x/y、shear x/y、depth，按18×16像素块均值降采样。
相机复用已有方形ROI与最近邻128缩放。第一次训练应检查ROI是否覆盖所需区域。

## 3. 真正训练一个初始policy

只有一个短包时，显式使用过拟合测试模式：

```bash
bash scripts/bag_bc.sh train --train local/bc/record001_dataset \
  --output local/bc/policy_record001_smoke --overfit-smoke --steps 500
```

这是实际PyTorch前向/反向/Adam更新，不是生成占位权重。
模型是小型RGB CNN＋触觉CNN＋状态融合，训练归一化的目标相对当前关节位置残差，
最终返回绝对目标。不是预训练骨干，不是SAC模型或已验证插孔控制器。
输出 `policy.pt`、`report.json`、`train_predictions.npz`；报告比较未训练模型、
保持当前关节位置和固定平均目标基线。权重内保存预处理契约和训练集统计。

有独立完整episode后使用验证集，例如：

```bash
bash scripts/bag_bc.sh train \
  --train local/bc/episode01 local/bc/episode02 \
  --validation local/bc/episode03 \
  --output local/bc/policy_run02 --steps 2000
```

这些episode目录需先分别导出。禁止把同一录包复制一份当验证集；内容episode指纹重复会拒绝。
归一化只根据训练集计算。单包模式没有独立验证指标，不能宣称泛化或任务成功。
暂不提供超大数据集流式训练、动作chunk、时序模型或预训练网络。

## 4. 模拟在线接收并推理

```bash
bash scripts/bag_bc.sh shadow --dataset local/bc/record001_dataset \
  --checkpoint local/bc/policy_record001_smoke/policy.pt \
  --output local/bc/shadow_run01 --loops 2
```

默认隔离localhost domain99。独立子进程按录包时间发布原始观测CDR；推理进程实际通过
ROS订阅、解码和维护有界历史，并用与导出相同的预处理生成输入。
不直接把NPZ观测送进模型冒充ROS接收。原始控制指令不回放。

回放参考消息提供源时间水位，以便接收方等待DDS跨topic乱序到达的数据，逐样本核验
离线/ROS输入哈希一致才推理。该握手机制属于录包验收工具，不是已实现的真设备时钟同步器。
真实设备在线入口及其自主采样调度仍待集成，不可以只改domain后宣称已可部署。

预测发布到 `/omi/shadow/prediction`（带时间戳的JSON诊断），不是机械臂命令消息；
状态在 `/omi/shadow/status`。默认每轮约第6秒故意暂停1秒检查STALE，不在无新参考时重复输出；
循环开始显式清空观测历史，结束自动退出。取消故意暂停用 `--pause-at -1`，
调速用 `--rate 0.5`。运行中Ctrl+C退出并清理子进程；不修改原包。

输出 `predictions.jsonl`、`report.json`、`replay.log`。验收检查每轮预测数完整、
输入一致、有限输出、无传输超时/控制topic；报告模型耗时和参考消息后的等待耗时。
这些不是从真实采样到执行的端到端延迟，也不是闭环效果。

## 5. 常见问题

- 输出目录已存在：换一个新的目录名，工具拒绝覆盖现有数据/权重/报告。
- 提示缺少marvin_msgs：核对本机overlay及Python/ROS版本，不复制其他机器install。
- 提示header晚于接收/倒退：先核查时钟，不绕过校验或强行改时间戳。
- 样本少：检查manifest丢弃原因，不要直接放宽过期阈值掩盖数据空洞。
- domain里出现控制topic：验收会失败；使用未被其他程序占用的隔离域，不启动控制器。
- 关节误差较小：单段轨迹本来变化小，“保持当前位置”也可能很强，必须对照基线和独立episode。
- 所有输出均标记shadow-only；尚未验证的动作单位、关节映射、时间语义和数据成功标签
  仍需采集方确认，不能把影子预测接到实机。

实现与限制见[纪传体](../docs/agent/training/evolution/bag-bc-shadow.md)，
本次真实数据结果见[编年记录](../docs/agent/training/chronicles/2026-10-03-bag-bc-shadow.md)。
