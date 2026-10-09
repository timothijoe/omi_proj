# 六维真机 HIL 环境、SAC 与 Actor/Learner

2026-10-09 更新：ROS 回合开始保留 Start 前持续积累的最近十帧，仅使旧策略候选失效。
输入完整且新鲜时不再重新预热约1秒；首次不足十帧、缺流或过期时仍等待有效输入。
需正常退出并重启 Actor 后生效，模型无需重训；
[操作与检查](async_rl.md#2026-10-09start-保留十帧输入)
· [实现与测试记录](../docs/agent/training/chronicles/2026-10-09-start-history-retention.md)。

## 2026-10-07：共享编码器与 HIL-SERL 参数对齐

开发归档与交接见[2026-10-07阶段记录](../docs/agent/training/chronicles/2026-10-07-shared-serl-resume.md)。

新 RL checkpoint 版本为 `omi-hil-sac-shared-serl-v2`。没有启动真机运动；
架构/恢复测试通过不代表策略已经具备插入成功率。

| 项目 | 新 RL 实现 |
|---|---|
| 输入 | 保留双相机、触觉网格、EEF、十帧历史与有效性掩码；当前离线入口 wrench 关闭 |
| 共享 | Actor 与双 Q 使用同一个 Encoder 对象，目标 Q 是独立副本 |
| 梯度归属 | Critic 优化器独占共享编码器；RL Actor 对融合特征 stop-gradient，只更新策略头 |
| 策略头 | 128→256→256→12，最后12维分别为6维均值和log_std |
| 双 Q 头 | 各自134→256→256→1（128维特征＋6维动作） |
| 激活与初始化 | 官方 MLP 的 activate_final=False：仅第一层后 LayerNorm(eps=1e-6)+tanh；Dense Xavier uniform，零bias |
| 分布 | tanh Gaussian，标准差范围[1e-5,5] |
| SAC | lr=3e-4，gamma=.98，tau=.005，Critic/Actor更新比2:1；双Q最小值target，无entropy backup，Actor用平均Q |
| 温度 | softplus参数化，初值.01，目标熵-3；用下一观测动作的熵更新 |
| 图像增强 | 默认开启，replicate padding=4随机裁剪；每样本每相机独立，同一十帧窗口共用偏移；只用于训练 |
| Batch | Learner/离线CLI默认256；显存受限可显式32，不会偷偷降级或缩放机器人动作 |

这仍是 PyTorch 适配实现，不是官方 JAX 数值等价复现。保留的差异包括：
当前多模态/历史融合适配器输出128维；融合编码器整体由Critic训练，而官方图像stop-gradient后
还有可训练的独立proprio投影；保留梯度范数5限幅、现有人工奖励/timeout bootstrap、动作坐标和幅度。
官方单帧USB配置无需照搬到我们的十帧输入上。没有增加夹爪。

参考：[官方网络配置](https://github.com/rail-berkeley/hil-serl/blob/main/serl_launcher/serl_launcher/utils/launcher.py)、
[MLP](https://github.com/rail-berkeley/hil-serl/blob/main/serl_launcher/serl_launcher/networks/mlp.py)、
[编码器](https://github.com/rail-berkeley/hil-serl/blob/main/serl_launcher/serl_launcher/common/encoding.py)。

v1 Learner/优化器不兼容v2，必须用新训练目录；原始采集数据可复用。
为避免破坏已有BC流程，demo_bc继续使用LegacyActor；v1 actor仍按旧结构加载推理，
但不能作为v2 Learner断点恢复。不是把旧权重硬塞进新网络。

训练CLI的Ctrl+C/SIGTERM变成停止请求，完整更新结束后保存再退出。
Learner在每50次更新发布完整模型/优化器/目标网络/RNG状态；正常结束保存最后进度。
更新内部异常（如OOM）不发布可能半更新的参数，保留上一个完整checkpoint。
这些机制不保证kill -9/断电零损失，也不自动接续机器人的物理动作。
采集续写、多目录合并及限制见[采集教程](rl_episode_collection.md#2026-10-07断点续采与分次采集)。

验证：72 passed、2 CUDA skipped；涵盖真实已采观测的CPU更新/重载/确定性续训，
共享参数优化器不重叠、目标编码器独立、图像增强时间一致性、更新中SIGINT保存/恢复无重复导入、
采集续写/孤立回合排除、多来源回合隔离及BC/Replay回归。未验证v2真机成功率或GPU batch256显存占用。

若当前只验证“按钮开始、成功/超时停止、回合外手柄复位”，先用
[人工RL回合采集](rl_episode_collection.md)。新入口不依赖模型或learner，
自动保留有效成功/超时回合，通过独立手动话题采集；下文旧Actor的单话题路由仍是另一条路径。

若当前只想先采集示范并验证模仿学习，使用[独立 Demo 采集与 BC](demo_collection_bc.md)：不需要先启动 learner 或提供策略，保留发送指令并允许后补 reward。本文的 `--offline-demo` 是另一条直接入 RL Demo 流的入口。

本入口在 `omi_hil_rl.hil`，不含夹爪动作、夹爪 Critic 或关节输入。
它提供 ROS 环境适配、真实多模态 Actor/双 Critic、两进程训练和人工回合审核。
目前通过软件与断开连接的 ROS 测试，尚未进行真机训练或插入成功率验收。

## 当前阶段与下一步操作

三项软件实现已完成，目前处于真机联调前阶段；尚未进行真机训练。
实现范围、测试证据及限制见 [docs 专题](../docs/agent/training/evolution/hil-actor-learner.md)。
以下是下一阶段的操作顺序，不是已经完成的现场验收记录。

1. 先运行本文的 fake 双进程示例，核对 `status.json` 中的 update 和 streams，
   以及 `episodes/<id>/ready.json`、`imported.json` 和策略文件是否产生。
2. 准备真实网络配置，启动 learner，再运行 ROS 只读预览。
   核对外部相机、触觉、EEF 和完整十帧历史；这里只生成预览动作，不产生训练 transition。
3. 现场短回合联调时核对开始、成功、超时和审核按钮。
   从开始按钮触发后计时，默认15秒包含历史预热；结束后停止发送，A/B分别保留或丢弃。
4. 核对匹配指令 ID 的回执、命令之后的 EEF 反馈和 action_source。
   先采集 `--offline-demo` 的成功全人工示范，再采集有效在线回合，核对分流。
5. 确认 learner 更新、权重发布与下一回合装载新版本，随后才开始记录真实插入效果。

| 检查对象 | 预期结果 |
|---|---|
| 成功回合 | 最后一条 reward=1、terminated=true |
| 有效超时回合 | 最后一条 reward=0、truncated=true，允许人工保留 |
| 保留整段 | 发布 ready.json，learner 导入后产生 imported.json |
| 丢弃整段 | 产生 discarded.json，不进入 replay |
| 初始离线全人工成功示范 | demonstration 增加，online 不增加 |
| 在线 policy / human | policy 只增加 online；human 同时增加两流计数 |
| 学习进度 | status.json 的 update 增加；Actor 在下一回合装载发布的策略版本 |

配置和命令在后文给出。此文档整理没有启动 ROS 预览、真机采集或训练。

## 回合与按钮

默认 Linux 手柄语义键码，均可在 config.json 修改；不是设备按键索引。

| 按钮 | 键码 | 作用 |
|---|---:|---|
| Menu/开始 | 315 | 启动新回合，立即开始 15 秒计时 |
| 成功键 | 308 | 成功，reward=1、terminated=true |
| 不成功结束键 | 307 | 提前结束，按截断处理，不标记成功 |
| RB 按住 | 311 | 人工六维动作接管；释放后用下一次新观测计算策略 |
| A | 304 | 回合结束后保留整段 |
| B | 305 | 回合结束后丢弃整段；运行中按下中止并丢弃 |

超时 reward=0、truncated=true，在 Critic target 中保留 bootstrap。
若截止发生在两次命令之间，停止发送，将最后一条有效 transition 标为截断，
仍可审核保留该有效前缀；不凭空新增动作或缺失的后继观测。
平时 reward=0；没有距离塑形奖励，也不训练成功分类器。
成功按键用单调时钟记录，按下时间必须早于截止时间，允许随后的反馈晚一点到达。
断线、坏观测、动作过期、控制端拒绝或修改命令等属于无效数据，整段丢弃。
开始计时包含约 1 秒的十帧历史预热；reset 仅清历史并等开始按钮，物理复位由人完成。
上电/reconnect 时已按住的按钮须先释放，避免误触发。

默认 `review=manual`。成功、失败、超时的有效回合都可保留。
只保留成功回合会减少 Critic 学习失败行为的机会；建议按数据是否有效来审核。
`review=auto` 会自动保留有效结束的在线回合；`--offline-demo` 仍只接受成功的全人工段。

## 数据与训练

Actor 把每个完整 transition 压缩写入 `run/episodes/<id>/000000.npz` 等文件，
内存只持有当前/下一观测；审核后原子发布 ready.json 或 discarded.json。
Learner 是 replay 的唯一写入者，逐条验证、导入已保留回合，并发布 imported.json 防重复。
整个回合用于**审核/交接**；训练每次从池中抽 **transition minibatch**，不是每 episode 更新一次。
数据交接发生在回合结束后，Learner 在 Actor 收集下一回合时可以持续训练已有数据。

分流规则：

- `--offline-demo` 的成功全人工回合只进入 Demo。
- 在线 policy transition 只进入 RL。
- 在线 human transition 同时进入 Demo 和 RL，失败也适用。
- 有两流时 batch 默认各半；真机 learner 默认等待两流都至少有 1 条数据。

既有 BC 数据中“未来 EEF 差分”是代理标签，不能作为 accepted_command transition 直接导入。
可以用新 Actor 的 `--offline-demo` 收集可训练的初始示范；如果已有完整 transition，
仍可用 [transition replay API](transition_replay.md) 离线导入。在线运行时只有 learner 能打开 replay 写入。

存储继续采用指定目录下的 memmap ring；不把容量对应的全部图像数组装入 RAM。
每条存当前和下一窗口，容量 1000 时数组约 2.3 GB；batch、模型和 OS 页缓存仍占内存。
目前没有历史帧去重。暂存和已审核的 episode 文件保留用于审计，会额外占磁盘；不自动清理。
单个环的覆盖也会覆盖老 Demo，Demo 不足时真机 learner 等待新人工数据；不等同于原版独立容量双池。

本机两进程使用目录交接与原子权重文件，不支持跨机器 AgentLace/gRPC。
Actor 只在回合边界装载最新策略，避免同一段内换版本。
Learner 支持干净退出恢复模型、目标网络、优化器和 replay；强制杀进程后的 dirty replay 会拒绝恢复。
导入 journal 可以补齐“已干净 checkpoint、尚未写 receipt”的中断；不声称支持任意断电事务恢复。

## 网络和动作

真实配方 `current9stack`：沿用冻结官方 ImageNet ResNet-10、当前 RGB＋过去 9 帧通道拼接、
双相机投影、触觉 CNN、EEF 位姿与 mask。历史首层和融合层可训练。
Actor 与 Critic 各有自己的可训练 encoder；两套 Q head 共享 Critic encoder。
Actor 输出六维 tanh Gaussian；Critic 是两个独立 MLP head，另有软更新 target 和自动温度。
没有 BC loss 或 BC 控制头初始化；可从既有 BC checkpoint **只提取观测统计和契约**。

动作顺序 dx/dy/dz/rx/ry/rz；内部为观测/policy 坐标系的 m/rad 旋转向量，网络动作为 [-1,1]^6。
默认每轴上限 1mm/√3 与 1°/√3，因此平移范数≤1mm、旋转向量范数≤1°。
这是分量有界的 SAC 动作空间，单轴速度较原手柄默认保守；不对 SAC 样本做事后径向投影。
人工映射也使用此分量上限，最终采用的动作按相同尺度归一化写入 replay。
`translation_step_m` / `rotation_step_rad` 是**每轴**上限。

SAC 默认 gamma=.98、tau=.005、lr=3e-4、alpha 初值 .01、target entropy=-3、两次 Critic 对一次 Actor。
Target 用 min Q、不加入 entropy backup；Actor 用 mean Q，对齐 RLPD 主训练的这一做法。
每 50 次 learner update 发布一次权重，退出时再发布一次。

## 软件闭环验证

以下只用显式 synthetic-test encoder 与 fake transport，禁止该 encoder 接入 ROS 真机契约。
在两个终端使用同一绝对 run 目录：

```bash
source scripts/env.sh
python -m omi_hil_rl.hil.learner --run "$PWD/local/hil-smoke" \
  --capacity 32 --batch-size 2 --min-demo 0 --updates 4 --wait-seconds 60
```

```bash
source scripts/env.sh
python -m omi_hil_rl.hil.actor --run "$PWD/local/hil-smoke" --episodes 2
```

`--min-demo 0` 仅用于软件合成测试；真机禁止绕过两个流的启动门槛。
fake 成功是脚本事件，不证明学会插入。

## 配置真实网络与 ROS 预览

使用已有无关节 current9stack checkpoint 和官方 backbone.pt 生成配置。
BC 路径使用实际存在的文件，EEF reference 和安装轴转换按现场配置选择：

```bash
source scripts/env.sh
python -m omi_hil_rl.hil.prepare \
  --bc-checkpoint /absolute/path/to/nojoint/best.pt \
  --pretrained local/pretrained/serl_resnet10/backbone.pt \
  --output local/hil-setup --episode-seconds 15 \
  --eef-reference raw --sdk-convention sdk-x-forward-z-left
python -m omi_hil_rl.hil.learner --run "$PWD/local/hil-real" \
  --config local/hil-setup/config.json --recipe local/hil-setup/recipe.json \
  --pretrained local/pretrained/serl_resnet10/backbone.pt --device cpu
```

本机 `local/cuda-env` 已补齐 train/bc/dev 依赖；调用 CUDA 时使用其 Python：
`local/cuda-env/bin/python -m omi_hil_rl.hil.learner ... --device cuda`。
ROS 终端先 source env_ros.sh，再用相同 CUDA Python 启动 actor。
换机器可执行 `local/cuda-env/bin/python -m pip install -e '.[train,bc,dev]'`。
无 CUDA 会报错，不隐式回退。
然后在另一终端启动只读预览：

```bash
source scripts/env_ros.sh
python -m omi_hil_rl.hil.actor --run "$PWD/local/hil-real" \
  --config local/hil-setup/config.json --device cpu --episodes 10
```

ROS 默认不创建机器人动作 publisher，不生成可训练 transition；预览不要求连接手柄。
真实执行需人工显式增加 `--execute`；示范采集另加 `--offline-demo` 并全程按住 RB。
此实现过程中没有连接或启动机械臂运动。

执行端需要已部署最新 `arm_delta_cmd`，只允许左臂 A、FRAME_BASE，
其他 gamepad/policy/manual 最终动作发布者必须停止。新 HIL actor 同时负责 policy 与 RB 仲裁。
HIL 人工动作和 policy 都发送到 `/omi/action/decision`，遵守该接收端的保护设置，
不使用已有 `/omi/action/manual_decision` 人工保护旁路。

每条命令带 `layout.dim[0].label=hil:<id>`；接收端在 `/omi/action/receipt` 返回采用及观察窗口回执。
当前执行方式是速度保持：策略名义增量乘以`policy_command_rate`换算速度，200Hz持续IK下发。
一个名义周期后，`velocity_window_sent`、`finished=true`表示观察窗口结束，
`velocity_hold_continues=true`明确表示速度还在保持。Actor等待匹配回执和命令之后的EEF输入，
随后产生下一条动作；故障拒绝不入池。成功或到时请求零动作立即停止。
取消、替换、拒绝/IK失败/限幅/保护/SDK拒绝会给出对应回执。
保存的动作是名义周期的采用命令，实际位移须结合反馈及观测时间理解；
不声称完成全部请求位移，`execution_confirmed`始终false。
策略断流默认0.25秒停止，完整参数见[控制教程](robot_controller.md#速度保持执行与参数)。

观测沿用 strict header/receive 时效，要求十帧完整、外部相机可用、EEF 新鲜，关节位固定零。
旧观测、推理超出 100ms、缺失回执或后继观测会中止并丢弃，不伪造 transition。

## 测试

软件测试覆盖按钮边沿、开始计时、成功/超时、审核、分流、timeout bootstrap、
无效数据整段预检查、干净 journal 恢复、单写者、SAC 参数更新、冻结骨干、权重重载，
以及 Actor/Learner 独立进程的磁盘交接。ROS 测试使用未连接节点与假 IK/SDK，不发送硬件动作。
本次软件42通过、1个CUDA case在CPU环境跳过；独立CUDA专项3通过。
ROS接收端/保护回归48通过，另有一项既有Jointfeedback schema测试因安装消息字段不匹配排除。
真实encoder＋合成输入的CUDA batch32两次更新通过，峰值已分配显存约813MiB；不代表策略收敛。
配置和初始网络审查产物位于 `local/hil-implementation-review/`，含 config.json、recipe.json、
actor.pt、learner.pt、gpu-smoke.json；未连接ROS或机器人。

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_hil_runtime.py tests/test_transition_replay.py tests/test_disk_replay.py \
  tests/test_hil_replay.py tests/test_demo_import.py tests/test_executed_action_sac.py
source scripts/env_ros.sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_hil_receipts_ros.py
```

## 速度保持执行回执

策略接收端现在把名义动作增量按 `policy_command_rate` 换算为速度，并在 200 Hz 保持。
`velocity_window_sent` 的 `finished=true` 只表示一个名义控制观察周期已结束，
`velocity_hold_continues=true` 明确表示速度仍在保持，直到下一条动作或停止条件。
Actor 可据此获取因果后继观测并产生下一条动作；回执不证明实际完成请求位移。
网络输出仍为名义周期的增量，训练记录应结合观测时间间隔理解实际位移。
策略断流由 `delta_timeout`（默认 0.25 秒，单调时钟）停止，零动作立即停止。
