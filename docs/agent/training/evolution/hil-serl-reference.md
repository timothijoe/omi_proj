# HIL-SERL 开源任务与 USB 实现参考

本文整理原版 `rail-berkeley/hil-serl` 的任务、奖励、传感器、遥操作和视觉网络，作为 OMI 后续开发的参考。它们尚未接入 OMI；OMI 当前能力以 [HIL 训练实现](hil-training.md) 为准。

## 来源与验证范围

核查日期：2026-10-02。本地参考仓库位于 OMI 的同级目录 `hil_serl_projects/hil-serl`，核查版本为 `c32939bccb65f3b8c43a9f9add3d322d4ab0264a`，参考工作树无修改。以下是源码静态核查结果，没有运行原版训练或连接 Franka、相机、SpaceMouse。在线来源为 [官方仓库](https://github.com/rail-berkeley/hil-serl) 和 [Franka 操作说明](https://github.com/rail-berkeley/hil-serl/blob/main/docs/franka_walkthrough.md)。这份说明针对原版 JAX/Franka 实现，不代表所有 LeRobot HIL-SERL 版本。

## GitHub 开源任务

[官方任务目录](https://github.com/rail-berkeley/hil-serl/tree/main/examples/experiments) 提供四个任务：

| 目录 | 目标 |
| --- | --- |
| `ram_insertion` | 将内存条插入插槽 |
| `usb_pickup_insertion` | 抓取 USB 接头并插入指定接口 |
| `object_handover` | 双臂之间传递物体 |
| `egg_flip` | 操纵锅具让物体翻面 |

它们是实机示例，需要机器人服务、摄像头、工作空间、示范和奖励分类器的配置。存在任务代码不等于提供了可直接运行的 MuJoCo 场景。RAM 和 USB 的官方操作说明较完整，其他两个任务的说明仍较简略。

## USB 动作、奖励与超时

动作过程为靠近 USB、夹住、提起、调整姿态、对准接口、插入；这些是任务的物理阶段，当前配置没有逐阶段的距离进度奖励。

USB 使用 `single-arm-learned-gripper`：动作 shape 为 `(7,)`，六维末端运动加一维夹爪。OMI 当前 `(7,)` 是七个关节增量，二者不能直接互换。固定夹爪任务可只保留六维末端动作；翻蛋任务的包装器进一步限制为三个动作分量，不能把所有开源任务都说成七维。

启用分类器时，成功条件是侧面局部图像的分类器 sigmoid 输出大于 `0.7`，同时 `obs["state"][0, 0] > 0.4`；这里首个状态分量是展平后的夹爪状态。成功奖励为 1，并结束回合；未成功通常为 0。配置的夹爪切换惩罚为 `-0.02`，包装器记录在 `info["grasp_penalty"]`，学习器用于夹爪分支的回报，不能简单理解为每步环境 reward 都减去该值。

`MAX_EPISODE_LENGTH=120`，环境默认 `hz=10`，名义交互时长为 12 秒。结束条件按步数判断；推理、图像获取和通信可能使实际用时超过 12 秒，复位耗时另计。成功可提前结束。基础 Franka 环境将达到步数上限也返回为第三项 `done=True`，第四项 `truncated=False`，没有统一额外超时罚分；训练脚本使用 `masks=1-done`，因此这个超时也会停止下一状态价值的引导。

OMI 当前到达任务则使用 `10*(d_before-d_after)-0.01+成功标志`，TCP 误差不超过 0.035 m 为成功；80 步、每步 0.1 秒仿真时间，未成功达到上限时返回 `truncated=True`，无额外超时罚分。SB3 经验采样保留超时的价值引导。详细机制见 [当前奖励与训练](hil-training.md)。

USB 复位代码会在目标插入位夹住接头、拔出，再移到复位区域松开。复位轨迹依赖具体场景，不能直接复用于 OMI。

## SpaceMouse 如何进入动作空间

原版使用桌面六自由度 SpaceMouse 遥操作，驱动读取 USB HID 输入，无需 ROS topic。`pyspacemouse.py` 将原始轴读数除以 `350`，得到通常在 `[-1,1]` 附近的控制量；这些表示控制帽的推动或扭转程度，不是末端测得的位姿。

`spacemouse_expert.py` 的单设备轴映射为：

```python
expert_action = [-state.y, state.x, state.z,
                 -state.roll, -state.pitch, -state.yaw]
```

`SpacemouseIntervention` 追加夹爪分量：左按钮约为 -1（闭合），右按钮约为 +1（打开），无按钮为 0（保持）。六维输入范数大于 `0.001` 或按下夹爪按钮时，人工动作整步替换策略动作；没有输入则执行策略动作。没有按比例叠加。实际替换的动作写入 `info["intervene_action"]`，用于录制和经验回放；同一设备也可用于采集完整示范。双臂有对应的双设备包装器。

USB 的 `ACTION_SCALE=[0.015, 0.1, 1]`，基础环境先将动作裁剪到动作范围，再计算：

```text
p_target = p_current + 0.015 * action[:3]    # 米
R_target = Exp(0.1 * action[3:6]) * R_current  # 旋转向量，弧度
gripper_command = action[6]
```

例如平移单轴 0.5 对应 7.5 mm 的目标增量；旋转单轴 0.5 对应 0.05 rad（约 2.9°）。驱动字段虽名为 roll/pitch/yaw，执行端将三维旋转输入解释为旋转向量，不是直接累计欧拉角。目标经工作空间限制后发送给 Franka 服务，底层控制器执行末端目标；目标增量不等于实际测得位移。

USB 包装顺序中 `RelativeFrame` 在 `SpacemouseIntervention` 外层：策略动作先从末端坐标系转换到基座坐标系；SpaceMouse 在内层接管，生成基座系命令。返回时 `intervene_action` 转换回策略的末端坐标系，保证经验动作与策略接口一致。

OMI 当前仅有键盘逐步覆盖与脚本教师，尚无 SpaceMouse 接口。将 SpaceMouse 的末端动作接入七关节增量环境，需要增加逆运动学或雅可比映射，并验证坐标、限位和真实执行语义。

## 观测与传感器

USB 基础环境读取 RealSense：`pyrealsense2` 采集、后台保存最新帧，再裁剪和缩放，摄像头图像通过本地采集进入 observation，不依赖 ROS 图像 topic。机器人状态在 Franka 服务侧经 ROS 接收，再由环境通过 HTTP `/getstate` 获取。`tcp_force` 和 `tcp_torque` 是机器人外力/力矩估计，不是独立触觉阵列；此 USB 配置没有额外触觉传感器输入。

基础状态中 `tcp_pose` 是 `(7,)`，位置 XYZ 加四元数；经过 `RelativeFrame` 和 `Quat2EulerWrapper` 后姿态改为欧拉角，位姿相对本回合复位姿态表达，速度转换至末端坐标系。

| 状态字段 | 展平前 shape | 含义 |
| --- | --- | --- |
| `tcp_pose` | `(6,)` | 位置与姿态 |
| `tcp_vel` | `(6,)` | 线速度与角速度 |
| `tcp_force` | `(3,)` | 外力估计 |
| `tcp_torque` | `(3,)` | 外力矩估计 |
| `gripper_pose` | `(1,)` | 夹爪状态 |

`SERLObsWrapper` 展平合计 19 维状态，并把图像提升为顶层字段；`ChunkingWrapper(obs_horizon=1)` 增加历史维。最终环境观测为：

```python
obs = {
    "state":           ...,  # (1, 19)
    "wrist_1":         ...,  # (1, 128, 128, 3)
    "wrist_2":         ...,  # (1, 128, 128, 3)
    "side_policy":     ...,  # (1, 128, 128, 3)
    "side_classifier": ...,  # (1, 128, 128, 3)
}
```

首维 1 是历史长度，不是 batch；训练批次会另加 batch 维。状态实际拼接顺序由 Gymnasium Dict 的键顺序决定，不应凭 `proprio_keys` 列表猜测位置。图像是 RGB `uint8`，范围 0～255；策略使用前三路相机图像和状态，奖励分类器使用 `side_classifier`，成功条件另检查状态。

共有三个物理相机：两个腕部与一个侧面。侧面相机的两种裁剪复用同一采集对象。相机输出为高 720、宽 1280，裁剪后再 resize 成 128×128；这里是 crop，不是数值限幅 `clip`。配置示例：

| 字段 | 原图裁剪 | 裁剪后 H×W | 最终 H×W×C |
| --- | --- | --- | --- |
| `wrist_1` | `[50:-200, 200:-200]` | 470×880 | 128×128×3 |
| `wrist_2` | `[:-200, 200:-200]` | 520×880 | 128×128×3 |
| `side_policy` | `[250:500, 350:650]` | 250×300 | 128×128×3 |
| `side_classifier` | `[270:398, 500:628]` | 128×128 | 128×128×3 |

OMI 当前 20 维数值观测没有图像、外力、力矩或夹爪状态，详见 [模型与任务](../../simulation/evolution/model-and-task.md)。

## 视觉网络规模与融合

USB 的 `encoder_type="resnet-pretrained"` 对应 ImageNet 预训练 ResNet-10。按 `resnet_v1.py` 的 64/128/256/512 通道、四个基本残差块计算，卷积骨干及归一化参数共 **4,905,792**，FP32 权重约 **19.6 MB**。这是当前架构的静态计数，不是整个 agent 或预训练 pickle 文件大小。

128×128 输入经过骨干得到 4×4×512 特征图；每路图像经 8 组可学习空间池化得到 4096 维，再投影到 256 维并经过 LayerNorm。每路的池化、投影和 LayerNorm 合计 **1,114,880** 参数（FP32 约 4.46 MB）。下文增加完整网络的源码静态估算；尚未在本机初始化完整 JAX 参数树或实测训练显存。

三路策略图像得到 768 维特征。`EncodingWrapper` 将 19 维状态通过 Dense、LayerNorm 和 tanh 投影为 64 维，因此真正融合特征为 **832 维（768+64）**，不是把原始状态直接拼接得到的 787 维。

骨干输出调用 `stop_gradient`，冻结预训练骨干；后面的空间池化/投影可通过价值网络训练。策略网络调用编码器时另设置 `stop_gradient=True`，阻止 Actor loss 对图像编码分支回传；不能把“投影模块可训练”解释成所有损失都会更新它。奖励分类器也使用预训练骨干和独立的分类头，不与动作策略的奖励输出混为一体。

### 总体结构与参数量

```text
三路 128×128×3 RGB → 共享 ResNet-10（冻结）→ 各路池化/投影（可训练）
                                             ↓
                                  三路各 256 维，共 768 维
19 维机器人状态 → Dense / LayerNorm / tanh → 64 维
                                             ↓
                              融合为 832 维
                       ┌─────────────────────┼─────────────────────┐
                  Actor 256→256      双 Critic 256→256      夹爪 Q 256→256
                  六维动作分布       加六维动作评价 Q       三种夹爪动作 Q
```

USB 实际通过 `utils/launcher.py` 设置 Actor、Critic 和夹爪分支隐藏层均为 `[256,256]`，使用 tanh 与相应 LayerNorm；不能只读取 `create_pixels()` 的夹爪默认 `[128,128]`。Actor 输出六维连续动作的均值和标准差参数；夹爪分支输出三种离散动作的 Q 值，两者共同生成七维环境动作。

`sac_hybrid_single.py` 为三路相机复用同一 pretrained encoder 对象，为 Actor、Critic 与夹爪分支复用同一融合 encoder。`common/common.py:ModuleDict` 明确说明 Flax 会处理共享子模块而不重复参数。以下按这一共享结构及当前 launcher 配置估算：

| 部分 | 参数数量 | FP32 权重，十进制 MB |
| --- | ---: | ---: |
| 共享 ResNet-10 骨干 | 4,905,792 | 19.62 |
| 三路池化、视觉投影及 LayerNorm | 3,344,640 | 13.38 |
| 19→64 状态投影及 LayerNorm | 1,408 | 0.006 |
| Actor MLP 与均值/标准差输出头 | 283,148 | 1.13 |
| 双 Critic MLP 与 Q 输出头 | 563,457 | 2.25 |
| 夹爪 Q 网络 | 280,323 | 1.12 |
| 温度参数 | 1 | 可忽略 |
| **在线学习网络合计** | **9,378,769（约 9.38M）** | **37.52** |
| 独立成功分类器 | 6,087,233（约 6.09M） | 24.35 |
| **在线网络＋成功分类器** | **15,466,002（约 15.47M）** | **61.86** |

静态计数方法：Dense 参数为 `(输入维+1)*输出维`，LayerNorm 为 `2*维数`；每路空间池化参数为 `4*4*512*8`，视觉 Dense 为 `(4096+1)*256`。Critic 的 ensemble 位于 MLP 上，两个 MLP 后的标量 Dense 是 ensemble 外的同一输出头，不把它重复计两次。

约 4.91M 骨干参数冻结，在线网络中剩余约 4.47M 参数可训练。Actor 对图像分支停止梯度，但状态投影位于这一停止梯度之后，仍可受 Actor loss 更新。完整参数树、optimizer 状态的实际分配和共享布局没有运行初始化复核；这里是按源码推算的结构规模。目标参数副本、优化器动量、梯度、中间激活、图像 batch 都会额外占显存，不能把约 62 MB 的权重估算当成训练显存需求。

## 实验显卡与训练时间

[原论文 4.3 节](https://arxiv.org/html/2410.21845v1#S4.SS3) 明确实验计算使用单张 **NVIDIA RTX 4090**。USB Grasp-Insertion 的论文训练时间为 2.5 小时，评估成功率 100%、平均完成时间 6.7 秒；这些是作者实验结果，不是当前 OMI 的验证。

论文的训练时间包含脚本复位、策略交互、暂停与计算，不能将 2.5 小时都换算为持续满速采集。原版 USB 的回合名义上限 12 秒是最大步数/频率，论文 6.7 秒是学成后评估的平均完成时间，两个数值并不矛盾。本次没有查到作者机器的系统 RAM 容量或 buffer 的运行内存峰值，不能用下面容量估算推断作者实际用了多少内存。

## 原版 Buffer 容量与内存估算

`examples/experiments/config.py` 默认 `replay_buffer_capacity=200000`、`batch_size=256`，USB 没有覆盖容量。Learner 创建独立的在线池与示范池，每池按 20 万个物理位置预分配；每批各抽 128 条。在线池收全部在线经验，示范池收离线示范和在线接管，因此在线干预在两个物理池中各有一份。两池满后都环形覆盖最旧位置。

20 万个交互步在 10 Hz 下名义上约为 5.6 小时；图像池还为回合开头、历史帧和 ring 边界使用辅助位置，因此物理位置数不是精确的可采样 transition 数。复位、停顿不持续产生策略 transition，几小时训练未必填满在线池；示范池通常增长更慢。

原版使用 NumPy 数组在 **CPU 系统内存** 中保存完整池，采样 batch 才通过 `jax.device_put` 传到 GPU。它通过以下方式减少开销：

- 存裁剪并缩放后的 128×128 图像，使用 uint8，每个通道 1 字节。
- `MemoryEfficientReplayBuffer` 对 `image_keys` 保存帧序列，重用相邻 transition 的当前/下一帧；采样时重建，两帧不会逐条各存一份。
- 容量固定，旧经验被覆盖。离线示范和在线数据混合采样，不必整池上传 GPU。

没有 JPEG/视频压缩，也没有把整池图像提前转成 256 维特征。原版 Actor 周期保存 pickle 主要用于存档和恢复，训练时 Learner 仍从 RAM 采样，没有提供直接从硬盘持续随机采样的这一功能。

单张 RGB 帧：`128*128*3=49,152` 字节，即 48 KiB。**当前 USB 代码的额外开销**是 `side_classifier` 不在用于帧复用的 `image_keys` 中，却仍保留在完整 observation 中，所以其当前/下一图像分别保存。

| 单池 20 万容量的图像部分 | 十进制 GB |
| --- | ---: |
| 三路策略图像，帧复用 | 29.4912 |
| 分类器图像，当前/下一帧两份 | 19.6608 |
| **一个池** | **49.152** |
| **两个池均填满** | **98.304（约 91.55 GiB）** |

这些只计算图像数组，不包括状态、动作、mask、采样临时数组、Python/JAX 与系统开销。预分配数组的逻辑体积、已写入数据和实际物理内存驻留要分别看，不能断言启动即占满 98 GB。未实测原版 RSS，系统的懒分配行为也会影响驻留时机。

按同一布局估算已写图像主体：在线池 5 万＋示范池 1 万约 14.75 GB，在线池 10 万＋示范池 2 万约 29.49 GB。回合辅助位置和其他开销另计。16/32/64 GB RAM 无法容纳两个填满池及程序开销；更小容量、减少不参与策略训练的图像或转磁盘存储可降低需求，实际设置应经测量。

## 磁盘方案与 OMI 已实现部分

用户提出完整经验写入硬盘并持续读取，OMI 已实现 [磁盘 HIL 经验池](disk-replay.md)：memmap 数组、一个物理 ring 加双流掩码、后台 batch 预取、读写锁、单 writer 锁和干净检查点恢复，训练可用 `--replay-backend disk --replay-capacity N`。操作和吞吐测试见 [磁盘教程](../../../../tutorials/disk_replay.md)。

参考任务与当前 OMI 的存储布局不同，不能直接复用 49.152 GB 的单池数字：

| 实现 | 图像主体布局 | 三路 RGB、20 万容量 |
| --- | --- | ---: |
| 原版三路策略图像 | 当前/下一帧复用 | 29.49 GB/池 |
| 原版完整 USB observation | 三路复用＋分类器前后图像 | 49.15 GB/池，原版有两池 |
| OMI 磁盘池若输入三路图像 | 三路当前与下一图像分存，一个物理池 | 58.98 GB 磁盘数组主体 |

OMI 当前环境尚无图像输入，只用合成三路 RGB 测试磁盘读写。第一版没有相邻帧去重/压缩，也没有独立异步写入队列；写入同步复制至 mmap，由 OS 回写磁盘。它避免容量级 RAM 数组初始化，但仍会使用页面缓存、当前和预取 batch，不是严格零内存或硬实时系统。

已记录的开发验证为 40 项测试通过、A 臂 200 步完成 SAC/BC 更新与覆盖、策略独立加载；RGB 小池缓存测试约 29.7 batch/s。长时运行、超内存冷盘性能、GPU 图像训练和 USB 仿真/实机未验证。部署前应测随机读取吞吐和控制循环延迟；SSD 比机械盘更适合随机采样，具体性能需按本机测量。恢复约束与证据留在 [磁盘开发编年](../chronicles/2026-10-02-disk-replay.md)，本页通过链接引用，避免重复维护测试细节。

## 源码定位与后续边界

下面路径均相对于同级 `hil_serl_projects/hil-serl`：

- `examples/experiments/usb_pickup_insertion/config.py`：动作尺度、相机、观测键、分类器阈值、回合上限与包装顺序。
- `examples/experiments/usb_pickup_insertion/wrapper.py`：侧面相机复用、复位、夹爪惩罚。
- `serl_robot_infra/franka_env/spacemouse/{pyspacemouse,spacemouse_expert}.py`：设备读数与轴映射。
- `serl_robot_infra/franka_env/envs/{franka_env,wrappers,relative_env}.py`：采集、动作执行、接管、坐标转换与结束语义。
- `serl_launcher/serl_launcher/wrappers/{serl_obs_wrappers,chunking}.py`：状态展平与历史维。
- `serl_launcher/serl_launcher/vision/resnet_v1.py`、`common/encoding.py`、`agents/continuous/sac_hybrid_single.py`：视觉网络、融合、冻结与 Actor 调用。
- `serl_launcher/serl_launcher/networks/reward_classifier.py`：成功分类器。
- `serl_launcher/serl_launcher/utils/launcher.py`、`common/common.py`、`networks/{actor_critic_nets,mlp}.py`：实际隐藏层配置、参数共享和计数依据。
- `examples/experiments/config.py`、`examples/train_rlpd.py`、`serl_launcher/serl_launcher/data/{replay_buffer,memory_efficient_replay_buffer}.py`：容量、两池、CPU 存储、GPU batch 与帧复用。

本轮仅整理文档。OMI 已有磁盘回放，但若开展 USB 仿真，仍需要接头和接口模型、接触和抓取物理、夹爪动作、图像观测、视觉网络、成功判定与复位；实机还需要适配设备控制和传感器。形成记录见 [首次核查与勘误](../chronicles/2026-10-02-hil-serl-reference.md)、[USB 资源与总体网络补录](../chronicles/2026-10-02-usb-resources-and-network.md)。
