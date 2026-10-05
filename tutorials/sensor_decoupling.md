# 独立传感器采集、录制与时间审计

当前现场入口为 `grid24x16` 触觉与腕部 ROI。备份提交为 `d317392`；改造前的数据和模型不重写。

## 启动采集

在项目根目录，每个终端都设置 `export ROS_DOMAIN_ID=13`，再分别运行：

```bash
bash scripts/start_daimon_live.sh camera --image-mode roi --transport network
bash scripts/start_daimon_live.sh tactile --transport network --tactile-wrench
```

已有同类采集器时先退出旧实例再启动；不要重复占用设备。2026-10-05验证时已将现场这两个采集器重启为新版；以后操作前先确认进程状态，不能由历史记录推断仍在运行。
这两个命令只管理传感器，不发布机械臂或夹爪控制。`network` 配置DDS发现范围，不改变设备FPS；domain是通信分组，不是频率。

## 触觉独立性

- A/B仍各一个进程，SDK配置仍为30 FPS。三场getter检查约60 Hz，各自按SDK帧号去重，避免两个30 Hz时钟相位不一致导致重复读取和跳帧。
- deformation、shear、depth分别验证和发布。某字段缺失、无效、帧号不同，不再整组舍弃。
- 六维力优先独立读取，最高30 Hz，不依赖其他字段通过检查。无帧号的SDK力，每次成功读取都会发布，但明确标注为主机读取、设备新鲜度未知；数值未变不等于数据陈旧，数值变化也不是时间标定。
- 默认grid模式不再为了发布数值额外读取raw/infer。需要raw时仍用 `--publish-raw`，其失败不阻止数值字段。
- SDK线程安全尚无保证，单指内部仍串行调用getter；异常隔离不等于阻塞隔离。某getter永久阻塞仍可能影响同指其他读取，未用不安全的多线程绕过。
- `--tactile-mode full` 和旧集成看板保留旧的匹配帧路径；本次独立模式针对当前使用的grid路径。旧看板不应解释schema4元数据为schema2同步快照。

## 腕部实时与录制分开

默认 `--camera-buffer record`：

| Topic | 含义 |
|---|---|
| `/omi/wrist/color/image_roi` | 最新已解码图像，BEST_EFFORT、depth=1，供实时显示/推理 |
| `/omi/wrist/color/image_roi/record` | FIFO处理的完整图像，RELIABLE、depth=32，供录包 |
| `/omi/wrist/metadata` | 每帧源帧号、主机完整JPEG接收时间、发布时间、排队与处理耗时 |
| `/omi/wrist/status` | 接收、组帧、队列、解码、实时覆盖与录制发布计数 |

完整JPEG队列同时限制60帧和64 MiB；可用 `--camera-buffer-frames`、`--camera-buffer-mib` 调整。
限制针对排队JPEG，不包括解码数组、DDS缓存等全部进程内存。满时丢最旧排队帧并增加 `queue_overflow_drops`；大于字节上限的单帧增加 `oversize_drops`。
实时路径可以跳过中间已解码帧，并用 `live_overwrites` 记录；这不代表录制路径漏发。
`--camera-buffer latest` 可回到只保留最新JPEG、不创建 `/record` 发布器的模式。

ROI仅改变ROS发布图像，设备到电脑仍传1920×1080 MJPG，不能据此认为设备网络负载变成128×128。
UDP源端丢包、设备未发送、进程崩溃、退出时队列未处理完仍可能造成缺帧；退出日志记录未处理队列。可靠DDS也不是永久无损存储保证。

## 时间与有效性元数据

每指沿用 `/omi/tactile_grid24x16/{a,b}/metadata`，新版为schema4逐字段事件：

- `field`、`side`、`sdk_frame_id`：字段和自身SDK帧号；无帧号为null。
- `host_read_started_ns`、`host_read_finished_ns`：本机读取区间。
- `header_ns`：对应标准ROS消息的header，用它关联元数据；不是曝光时间。
- `source_timestamp_ns=null`：SDK未提供可信源时间，不伪造。
- `freshness_verified=false`：不声称已经测得设备端新鲜度。
- `counters`：成功读取、发布、重复帧读取、观察到的SDK帧号跳跃、序列重置与无效读取。

每指status还包含各字段独立错误和最近有效读取时间。重复读取去重不等于丢失新帧；`source_sequence_gaps`也只说明观察到的SDK序列跳跃，不能独自定位设备端原因。

腕部status中的 `completed_sequence_gaps`、过期/容量淘汰/被新帧越过的未完成帧、`decode_failures`、队列丢弃分别描述不同环节，**不要把它们相加当作独立丢帧数**。

## 录包与转换

[录包教程](demo_bag_dataset.md)的命令不变。白名单已增加腕部 `/record`、腕部metadata/status、双指metadata/status。
独立手柄继续自己运行，录包器不接管手柄。

`passive_preview`、`passive_bc`、`zero_preview`发现腕部 `/record` 时优先使用它；旧包自动沿用旧topic，不合并两份同帧图像。
新增转换产物记录十个历史槽内各字段的接收时间、header、SDK帧号（有元数据才有）、时间年龄和主机header跨度。
可为 `passive_preview` / `passive_bc` 添加：

```text
--max-tactile-skew-ms 100
```

这是可选的主机header跨度上限，默认只记录跨度、不额外过滤，以保持旧转换条件可复现。它不是设备曝光同步阈值，100 ms也不是经过任务验证的最优值。
原有因果选择、数据形状/有限值和时效检查仍在。部分原始数据被保留，不意味着当前网络已经支持缺字段训练。
BC只要求观测与后续指令配对；RL式预览还检查下一观测的EEF晚于指令。两者不能互换为已执行动作回执。

查看器新增底部字段时间面板，并支持当前 `passive_bc` 的 `dataset.json`；BC禁用next observation按钮。
老数据集没有该面板的审计信息时显示unknown，需要重新转换才能补充时间；旧bag没有SDK帧号元数据时不能补造帧号。
已有NPZ、模型和默认模型入口不被修改。

## 只读检查命令

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
python3 scripts/audit_sensor_streams.py --duration 10 --output /tmp/sensor-rates-new.json
```

输出必须不存在。工具不打开SDK、不发布控制，只订阅图像、触觉、力和状态，预热2秒后统计。
它使用BEST_EFFORT探针，探针少收不能直接认定发布端丢失，需对照生产者计数和bag。

本轮实测、限制和产物见[验证记录](../docs/agent/hardware/chronicles/2026-10-05-sensor-decoupling.md)。

## 实现与RGB时间检查说明

需要继续开发时，先看[采集解耦实现方法](../docs/agent/hardware/evolution/sensor-decoupling.md)，包含SDK读取顺序、字段去重、腕部线程与队列、双路发布和转换数据流。

外部RGB入口的 `header_age_ms` 与构造观测时的 `source_receive_age_ms` 含义不同；两者差大不证明没有真实积压。当前手柄策略wrapper的RGB 500 ms分别约束两项，不是跳过header。外部RGB专用接收时间策略尚未实施，不能使用全局诊断模式代替正式发布检查。见[时间基准纪传体](../docs/agent/hardware/evolution/sensor-time-alignment.md)。
