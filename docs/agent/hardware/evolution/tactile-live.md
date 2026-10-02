# rosbag 播放时的触觉向量显示

稳定入口及 `real.tactile_live` 保留 `d017387` 实现与外部SDK默认路径，不自动迁移。
独立包重建另用 `view_observation_bag_migrated.sh` / `real.tactile_live_migrated`，
默认SDK为 `local/vendor/daimon_tactile`。见[迁移方案](tactile-reconstruction-migration.md)。
两入口不能在同一domain同时运行。SDK原生字段另用[新看板](sdk-native-dashboard.md)，
入口 `view_sdk_observation.sh` 默认domain88，不从图像重建。

`real.tactile_live` 提供两个独立进程：`fields` 从双指 raw 和固定零载荷基准调用 Daimon
CPU FlowTracker/Decomposer；`dashboard` 订阅处理结果并绘制双行 raw/deformation/shear。
不创建厂商 Sensor，不连接 USB，不发布机器人控制命令。操作见
[ROS 教程](../../../../tutorials/ros_observation_interface.md#播放时实时查看触觉向量)。

## 相机与触觉合并模式

`scripts/view_observation_bag.sh` 在同一播放器中回放双指 raw、头部和腕部 RGB，
`dashboard --with-cameras` 发布 `/omi/observation/dashboard`（`1792×740 rgb8`）。
左侧 640 像素宽放两路原图预览与 128×128 ROI；右侧保留完整 1152×740 触觉面板。
`camera_panels` 复用 observation 的 ROI 边界计算，缩放沿用旧人用相机工具的 Lanczos，
与策略 observation 的最近邻缩放不同。原图保持宽高比，128 小图在合成图中不放大。

合并模式使用独立缓存键和四路 topic 白名单。所有输入共用播放进度，但传感器源时间戳
不同，显示为每路最新到达值，不声称逐帧同步。各路分别显示时间戳、接收年龄与过期状态。
默认域号与纯触觉模式相同，运行合并模式前应停止旧的纯触觉播放器。
最新证据见[合并显示编年](../chronicles/2026-10-02-camera-tactile-dashboard.md)。

## 数据契约

- 输入 `/tj/dm_sensor/{a,b}_raw`，要求非零 header 时间戳、与基准一致的 mono8 shape。
- 输出 `/omi/tactile/{a,b}/deformation` 和 `shear`：带原始 header 的 `32FC2` Image，
  当前 SDK 输出为 `288×384×2 float32`，必须全有限，保持有符号数值。
- `/omi/tactile/{a,b}/raw` 转发参与计算的 raw，与两个数值场使用相同时间戳。
- `/omi/tactile/{a,b}/metadata` 为 JSON String：schema_version、逻辑侧、外部确认的
  serial/physical_side、source_timestamp_ns、received_timestamp_ns（本机 Unix 时钟）、
  baseline_id（metadata 和两张 NPY 的 SHA256）、处理版本、SDK Python 文件哈希、
  shape/dtype、valid、处理耗时、未标定单位和图像坐标约定。
- SDK Python 哈希不包含原生库或外部模型；不是完整 SDK 安装的指纹。
- 异常帧记录错误并不发布；dashboard 在最后一次完整接收超过 0.5 秒后标记 STALE。
  该年龄是墙钟接收年龄，不是历史 bag 时间戳与当前系统时间的差，也不是策略新鲜度契约。
- `/omi/tactile/dashboard` 是 `1152×740 rgb8`，仅供 RViz；A/B 分别显示源时间戳，
  不保证双指同时采样。每侧仅绘制时间戳完全匹配的 raw、两场及 metadata。

## 性能和回放

默认目标 10 Hz。raw 订阅为 best effort/depth 1，处理慢时跳过旧帧；输出数值为
reliable/depth 2，Fast DDS 使用异步发布，独立绘图进程避免直接在数值计算回调里渲染。
这是回放诊断工具，不承诺完整录制、零丢帧或硬实时。renderer 固定 step=16、scale=2、
deadband=0.2、最大 24 px；超长箭头红色显示。数据未做逐帧归一化。

`scripts/view_tactile_bag.sh` 默认使用 localhost 的独立 ROS domain 87，循环回放，启动
独立 RViz。可与已有相机窗口并行，但两份播放器不共享进度或暂停控制。
`OMI_TACTILE_ROS_DOMAIN_ID` 可覆盖域号；这个域应仅用于本地回放。

压缩 bag 先经 `real.tactile_replay_cache` 在私有临时目录解压，再只复制 A/B raw CDR 到
`local/tactile/replay_cache/`。源 bag 目录不写入，避免多个压缩播放器覆盖同一解压文件。
缓存键使用源路径、metadata 哈希、文件大小和 mtime；不是完整原始数据内容哈希。
缓存缺少一侧时拒绝发布完成结果。缓存首次构建需要整份 MCAP 的临时磁盘空间，
`record010` 最终 raw 缓存约 110 MB。播放起点是首个 raw，而非原 bag 的首个消息。

## 范围

这是触觉向量查看器，不是完整触觉验收 dashboard：还没有 depth/delta、wrench 曲线、
fid 或完整库存报告，没有把向量场加入 observation/replay。物理坐标和单位标定仍待完成。
当前验证证据见[回放编年](../chronicles/2026-10-02-tactile-live-replay.md)。
