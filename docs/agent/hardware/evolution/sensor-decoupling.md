# 触觉与腕部采集解耦：实现方法与边界

更新：2026-10-05。本文记录已实现的当前真实 `grid24x16` 采集路径；开发过程与实测原始产物见[编年体](../chronicles/2026-10-05-sensor-decoupling.md)，启动和参数见[教程](../../../../tutorials/sensor_decoupling.md)。改造前备份为 `d317392`，该提交不包含随后实施的解耦改动。

## 要解决的问题

此前触觉按一组字段取数并要求帧号匹配，某字段缺失或帧号不同会导致其他有效字段一起丢弃；无帧号六维力也不应依赖三场同步成功。腕部仅保留最新JPEG适合实时显示，但处理稍慢时中间帧会被覆盖，不适合作为唯一录制来源。

现在把“尽量保留各传感器原始有效数据”和“下游构造完整模型观测”分开。采集端独立保留，转换和策略端仍执行各自的数据契约；这不代表网络已支持缺字段输入。

## 触觉：每指一个进程，字段独立校验与发布

真实grid入口由 [node.py](../../../../ros2/omi_sensors/omi_sensors/node.py) 分派到 [independent_tactile.py](../../../../ros2/omi_sensors/omi_sensors/independent_tactile.py)。旧full和模拟路径保留旧实现，不能把新行为推广到所有模式。

1. A/B分别连接SDK。每指内部串行调用getter，不假设厂商SDK线程安全。
2. `IndependentReader` 为每个字段分别维护最后帧号、错误、最近有效读取时间和计数。三场分别检查数组形状、有限值，并降采样为24×16数值网格。
3. SDK仍配置30 FPS，主循环约60 Hz检查三场；同一字段重复帧号只计数不发布，新帧独立发布，序列跳跃与重置分别记录。不同字段帧号不必相等。
4. 开启wrench后，力排在字段读取顺序首位，独立按最高30 Hz调度。其他字段校验失败不会撤销已读取的力，也不阻止其下一轮调度。
5. SDK无帧号的力，每次有效读取都发布六维数值；记录 `changed_since_previous_read`，但不因数值不变判定陈旧。`sdk_frame_id`、`source_timestamp_ns` 为null，`freshness_verified=false`。发布频率不能证明设备内部力估计更新频率。
6. 默认数值路径不额外读取raw/infer；raw显式开启后独立处理。字段异常只落在该字段状态；持续没有有效字段发布则进入重连流程。

独立调度不等于并行读取：单个getter永久阻塞仍可拖住同指其他字段。当前没有厂商线程安全及取消接口依据，因此没有新增并发SDK调用。

## 字段时间与数据关联

各字段使用自身主机读取结束时间作为ROS header。每指原metadata topic输出schema4逐字段事件，记录 `field`、`side`、`sdk_frame_id`、`host_read_started_ns`、`host_read_finished_ns`、`header_ns`、处理耗时与计数。标准消息和metadata用topic/字段及相同header关联。

status按字段报告读取、有效读取、发布、重复读取、序列跳跃、无效读取、错误及最近有效读取时间。header不代表曝光时间；不同字段header不一致是独立读取的正常结果，也不能用主机header差证明设备采样已同步。

## 腕部：接收、解码、实时发布分离

实现位于 [wrist_live.py](../../../../ros2/omi_sensors/omi_sensors/wrist_live.py)、[wrist_wire.py](../../../../ros2/omi_sensors/omi_sensors/wrist_wire.py) 和 [frame_queue.py](../../../../ros2/omi_sensors/omi_sensors/frame_queue.py)。

```text
设备 MJPG 1920×1080，申请30 FPS
  → UDP接收线程：组装完整JPEG，记本机接收时间与源帧号
  → 有限JPEG FIFO：默认最多60帧且最多64 MiB
  → 解码线程：依次解码、生成ROI、发布可靠record流
                    └→ 更新“最新已解码图像”槽
  → 主循环：取最新槽，发布实时流
```

| 路径 | ROI topic | QoS及用途 |
|---|---|---|
| 实时 | `/omi/wrist/color/image_roi` | BEST_EFFORT，depth=1，显示/推理可跳过中间帧 |
| 录制 | `/omi/wrist/color/image_roi/record` | RELIABLE，depth=32，按FIFO处理顺序发布 |

full模式对应 `image_raw` 与 `image_raw/record`。默认 `--camera-buffer record`；`latest`模式只保留最新JPEG且不创建record发布器。ROI是在本机解码后产生，设备网络仍传1080p JPEG。

队列同时受帧数和字节数约束，溢出丢最旧排队帧，超大单帧单独丢弃并计数；64 MiB仅限制排队JPEG，不是整个进程内存上限。实时槽被覆盖计入 `live_overwrites`，不等于record漏发。

metadata记录完整JPEG本机接收时间、源帧号、发布时间、排队与处理耗时。status区分完整帧序列空洞、未完成帧淘汰、解码失败、队列溢出与实时覆盖；这些计数可能描述同一次缺失，不能直接相加。退出报告未处理队列；没有承诺退出前全部排空。

## 录包、离线转换与可视化如何衔接

[demo.py](../../../../src/omi_hil_rl/hil/demo.py) 白名单加入腕部record、metadata/status和双指metadata/status。[sensor_alignment.py](../../../../src/omi_hil_rl/training/sensor_alignment.py) 为原接收时间因果采样补充逐字段时间审计。

`passive_preview`、`passive_bc`、`zero_preview`发现record topic时只选该腕部流；旧包回退实时topic，不合并重复图像。转换保存十个历史槽的字段header、接收时间、可获得的SDK帧号及年龄。`--max-tactile-skew-ms`默认不启用额外过滤，指定后约束主机header跨度，不能当作曝光同步判据。

BC匹配观测与后续指令；RL式预览仍要求下一观测的EEF晚于指令，两者都不等于真实执行回执。查看器增加底部时间审计并支持passive BC格式；BC无next observation时禁用对应切换。旧包缺失的SDK元数据不能补造，旧模型和数据不自动重写。

## 已验证与仍待验证

最终10秒只读短测：三场约30 Hz、力约29.6 Hz、腕部实时与record约30 Hz。对应status窗口未见新增三场序列跳跃或腕部组帧/队列损失。10秒录包请求中2280条传感器消息均匹配对应metadata；转换和可视化已验证，相关软件测试90项通过。这些是本次实现阶段已有结果，不是文档更新时重新测试。

短测不能保证设备、UDP、DDS、录盘长期零丢失；力内部缓存/推理时延未知。后续独立探针曾看到腕部单次约291 ms的header age，不能把短测结论写成永远无积压。外部RGB源时钟与接收时钟问题另见[时间基准纪传体](sensor-time-alignment.md)，不属于本次已完成的采集解耦修复。
