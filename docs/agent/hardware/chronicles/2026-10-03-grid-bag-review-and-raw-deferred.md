# 2026-10-03：小矩阵实录回放、raw缺失解释与开发暂缓

## 范围与结论

检查用户提供的`oct3_011/bag_002.zip`，MCAP约10.016秒、15个话题、18279条消息。
完成逐条反序列化检查及观测字段形状/有限性检查，无记录的解码错误。
用独立domain96在RViz显示外部相机及128裁剪、腕部128 ROI、双指网格箭头、depth、
关节驱动3D模型和左末端坐标轴；截图与用户反馈确认显示可用。未回放任何控制topic。

| 数据 | 包内证据 |
| --- | --- |
| A deformation/shear/depth | 各281帧，约28.05 Hz；两向量场16×24×2，depth16×24 |
| B deformation/shear/depth | 各277帧，约27.65 Hz；最长header间隔约107 ms |
| 双指wrench | 各0条消息，原因未定位，不能宣称SDK六维力已经接通 |
| 腕部ROI | 293帧，128×128，约29.25 Hz；最长header间隔81.7 ms，不二次裁剪 |
| 外部彩色 | 245帧，从包起点1.849秒开始；出流期间约30 Hz，不应按全包均值判为持续24 Hz |
| 关节反馈 | 1493条，从2.543秒开始；之前预览为中立占位，不是真实姿态 |
| 左末端 | 9023条，从0.879秒开始，frame为base_link；模型/TCP标定仍未验收 |

raw/infer、触觉metadata/status和CameraInfo未录入本包。没有metadata/status，
不能据此区分wrench未开启、SDK返回不合规或其他采集/录制原因。

## 时间与预览边界

触觉header比录包接收时间快约22 ms（接收减header的中位数约-22 ms），
提示时钟/时间戳语义不一致，不能解释为负传输时延，也不能把22 ms直接当成精确校正量。
旧预览严格检查因此拒绝处理。本次仅local临时适配按录包接收顺序生成10 Hz预览，
保留原header、显示CLOCK OFFSET/FUTURE提示，不修改原包、不自动校准时间。
这不是训练同步或长期吞吐验收。训练需要处理起始覆盖缺口及跨机同步。

## raw缺失为何发生

当前`start_daimon_live.sh tactile --transport network`默认grid24x16。
代码`node.py`在该模式跳过raw/infer publisher，`tactile_grid.py`只保留数值字段；
因此raw缺失是发布策略导致，不是接收端订错名称，也不证明传感器没有原图。
full模式仍使用`/omi/tactile/{a,b}/raw`。此包没录raw，无法通过换topic或重放恢复。

用户要求先记录，等后续指令再开发。建议的“小矩阵＋可选raw”及`--publish-raw`
均尚未实现，命名/分辨率/帧率等留待确认。本轮文档更新不改代码、不重启采集。

## 本机证据

- `local/review_oct3_011_002/audit.json`：话题计数、尺寸、时间间隔、时间差。
- `local/review_oct3_011_002/desktop.png`：RViz显示截图。
- `local/review_oct3_011_002.py`与`local/review_oct3_010_004.py`：临时本机检查/预览代码，
  有本地路径依赖，不是已产品化的可移植回放入口。
- `local/review_oct3_011_002/receipt_order_preview_v1/manifest.json`：接收顺序预览声明。

上述local证据和缓存被Git忽略；不把包、截图或SDK提交仓库。
最新能力见[采集纪传体](../evolution/sensor-collection.md)与
[分辨率纪传体](../evolution/tactile-resolution-and-throughput.md)。未commit/push。
