# 双指六维力/力矩：实时查看与完整历史记录

从项目根目录运行：

```bash
bash scripts/view_wrench_live.sh
```

默认订阅 domain13 的 `/omi/tactile_grid24x16/a/wrench` 和
`/omi/tactile_grid24x16/b/wrench`（`geometry_msgs/WrenchStamped`），打开独立 RViz。
已有传感器发布者继续运行；本工具不启动采集、SDK或机械臂控制。
当前现场已经有 wrench，无需重启采集。其他现场若只有 WAITING，需要在采集端显式开启
`--tactile-wrench`，详见[触觉发布开关](tactile_grid_transport.md)。

## 实时与历史

左右分别为 A/B，四个图分别显示两指的三个力分量和三个力矩分量。
RGB曲线分别对应 X/Y/Z；力图最小范围默认为`[-2,2]`，力矩图为`[-0.5,0.5]`，单位仍为SDK原值。
范围以零为中心，范围内的小波动不会改变比例尺；超出后按两倍档位扩大并显示实际刻度，
不会随每个样本的小变化连续伸缩。参数指定的是完整跨度，不是单侧上限。
大样本退出实时窗口后可缩回较小档位，但始终保留最小范围；四幅图各自判断超限。
修改前已经运行的看板需要停止后重启，默认启动命令即可启用新比例尺。
实时显示数值、向量模长、接收频率及接收年龄，默认最近15秒、刷新5Hz。
默认0.5秒没有新消息标记 STALE；缺数据标记 WAITING，非有限值标记 INVALID。
旧数值不作为实时值显示；曲线在无效值及超过断流阈值的间隔处断开。

终端打印本次独立目录 `local/wrench_live/session-*`。**每条收到的wrench都写入磁盘**，
不随15秒可见窗口删除；JSONL约每次刷新时flush，正常退出会关闭文件。
这记录的是订阅端实际收到的消息，不保证发布端所有消息零丢失，也不是掉电事务存储。

| 文件 | 内容 |
| --- | --- |
| `samples.jsonl` | 每条六维原值、A/B、header及接收ROS时间、单调时钟相对秒数、frame、valid/error |
| `metadata.jsonl` | 收到的厂商来源/基线/身份/wrench同步声明，附接收时间；不推断与某条wrench严格同帧 |
| `manifest.json` | 话题、domain、分量顺序、单位和记录契约 |
| `status.json` / `dashboard.png` | 最新状态/实时图 |
| `report.json` | 停止后的消息数、无效数和时长 |
| `history.png` | 停止后自动生成的整段历史图 |

按 Ctrl+C 或关闭本次 RViz 停止，原始 JSONL 保留。整段历史图采用固定数量的时间分箱，
每箱保留各分量最小/最大值，避免短时尖峰因均值或抽点消失；精确时刻与原数值以JSONL为准。
全程图生成采用两次流式读取，内存不会随录制总长度增长。缺失区间不补零。

重新生成已有记录的全程图（也可在程序异常退出后恢复绘图；需确保JSONL最后一行完整）：

```bash
bash scripts/view_wrench_live.sh --review-session local/wrench_live/你的会话目录
```

这只读取本地记录并更新派生 `history.png`，不启动ROS节点、不修改原始记录。

## 可选参数

```bash
# 观察最近60秒，历史仍保存全程；10分钟后自动停止
bash scripts/view_wrench_live.sh --window 60 --duration 600

# 显式设置最小范围：力[-2,2]、力矩[-0.5,0.5]（当前默认）
bash scripts/view_wrench_live.sh --force-min-span 4 --torque-min-span 1

# 只记录并保存PNG，不打开RViz
bash scripts/view_wrench_live.sh --no-rviz --output local/wrench_live/my_session

# 其他domain或话题
bash scripts/view_wrench_live.sh --domain 13 \
  --topic-a /omi/tactile_grid24x16/a/wrench \
  --topic-b /omi/tactile_grid24x16/b/wrench
```

指定输出目录必须是新目录，拒绝覆盖已有会话。metadata默认订阅各wrench父路径下的
`metadata`，缺metadata不阻止原始wrench记录。诊断图话题为 `/omi/live_wrench/dashboard`；
同一domain一次运行一个此看板，避免两个图像发布者混流。

比例尺参数保存在manifest，停止后的历史图及后续重建沿用本次设置。
重建时可以通过`--force-min-span`/`--torque-min-span`覆盖显示范围，原始数值不变。

需要ROS Jazzy、项目Python环境中的NumPy/Pillow及RViz；不需要厂商SDK和Marvin消息。
默认Python为`.venv/bin/python`，可用`OMI_WRENCH_PYTHON`显式覆盖。

## 数值含义

顺序为 `Fx,Fy,Fz,Tx,Ty,Tz`。直接显示与记录消息原值，不做基线扣除或方向变换。
厂商物理单位、轴向、wrench真实采样新鲜度和与三场同帧关系尚未确认，因此不标成N/N·m，
也不能把本工具的接收年龄当成传感器曝光到屏幕的延迟。图上的合量沿用相同未标定单位。

2026-10-05现场无GUI约12秒收到A310/B316条，有限值检查通过；RViz约15秒启动/退出与
真实记录另验。最小比例尺版11项测试通过，约6秒现场收到A140/B142条，
绘图及记录通过。当前结果见[功能机制及证据](../docs/agent/hardware/evolution/wrench-live.md)。
