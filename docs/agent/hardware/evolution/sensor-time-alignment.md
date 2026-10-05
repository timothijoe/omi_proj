# RGB与触觉的时间基准、接收新鲜度和策略检查

更新：2026-10-05。事实与讨论过程见[编年体](../chronicles/2026-10-05-rgb-clock-and-receive-age.md)。触觉与腕部已完成的采集实现见[解耦纪传体](sensor-decoupling.md)。

## 两种年龄不是同一段时延

| 名称 | 当前计算 | 含义 |
|---|---|---|
| `header_age_ms` | `(receive_ns - header_ns) / 1e6` | 消息进入观测系统时记录；包含源header语义、跨机时钟偏差和到回调的实际耗时 |
| `source_receive_age_ms` | `(reference_ns - selected_receive_ns) / 1e6` | 构造观测时，所选数据在本机接收后已经过去多久 |

本机receive时间在订阅回调获取锁后记录，不是网卡收到数据包的时刻。header通常是驱动给图像的帧时间，不一定是发送时间。两者也都不是神经网络推理耗时。

`rgb`指外部/头部第三方相机 `/camera/camera/color/image_raw`；`wrist_rgb`指腕部图像。外部RealSense header与腕部完整JPEG本机接收header的起点不同，不能把二者的年龄差解释成两台相机真实端到端延迟差。

## 当前实现

[stack_shadow.py](../../../../src/omi_hil_rl/training/stack_shadow.py) 在入口检查header，在buffer采样时另检查接收年龄；[eef_bc_grid.py](../../../../src/omi_hil_rl/training/eef_bc_grid.py) 按本机接收时间选择不晚于参考时刻的最新数据。

- `rgb:old_header`：入口认为外部RGB header太旧。
- `missing_or_stale:rgb`：采样时缺少可用RGB或本机接收后已经超时；不能直接归结为header问题。
- 当前 `run_wrench_policy_gamepad.sh` 默认传 `--rgb-max-age-ms 500`，对外部RGB的header和接收年龄两项分别生效。底层默认仍是250 ms，不能说所有入口都默认500 ms。腕部/触觉250 ms、EEF50 ms的检查不因此放宽。
- 全局 `receive-only-diagnostic` 仅用于诊断；它不是已经实现的“只豁免外部RGB header”上线开关。候选动作发布禁止该诊断模式，passive BC实时路径仍要求strict。

## 如何理解源时钟疑点

外部相机读到 `global_time_enabled=true`、`use_sim_time=false`。RealSense GLOBAL_TIME把设备时钟映射到相机所连接主机的系统时钟，并不自动同步两台电脑。定义见[官方时间戳枚举](https://github.com/realsenseai/librealsense/blob/master/include/librealsense2/h/rs_frame.h)。本机报告NTP同步也不能证明源主机同步。

旧包存在负header age，支持继续检查时钟/时间戳语义；当前较大的正年龄仍可能包含真实排队。`frames_queue_size=16`只是配置容量，不是已测得积压16帧。

## 已讨论、尚未实施的方向

用户希望检查两种年龄的差异，避免源时间戳不准导致新收到的RGB被误判。可考虑为外部RGB提供显式的接收时间新鲜度策略，同时保留原header与异常状态，训练和推理采用一致的对齐语义。

**不能仅凭两种年龄相差很大就宣布图像没有延迟。** 源时钟落后400 ms与数据实际积压400 ms后刚收到，都可能呈现较大header age、很小receive age。合理状态是“接收新鲜，源时间未确认”，不是“端到端无延迟”。

后续若实施，应只针对外部RGB明确配置，保留接收超时、形状/有限值、因果采样和完整历史检查，监测到达间隔与突发补发。仍需核对源主机时钟及驱动时间戳语义，或独立测量曝光到接收延迟。本次仅记录方案，未加入自动豁免规则、时钟偏移补偿，也未修改相机参数。
