# 2026-10-02：rosbag 实时触觉向量回放

## 目标和实现

用户要求先保存已有成果，再让播放 bag 时可查看 A/B deformation/shear。首先在当前
`oct_02_branch` 创建本地提交 `c8b6642`，保存 observation、触觉离线处理、磁盘 replay、
文档和测试；提交前完整测试 `50 passed, 1 skipped`。日志加入忽略，未提交大资源。

随后增加 `tactile_live` 的数值计算和独立 dashboard 两个进程、32FC2 解码、源时间戳
配对、基准/身份 metadata、固定箭头比例、过期提示，以及 RViz 配置和一条命令的播放入口。
完整当前机制见[纪传体](../evolution/tactile-live.md)。

发现同时播放压缩 bag 时，相机和触觉播放器会争用源目录中的同名解压 MCAP。新增私有
临时解压和 raw-only 缓存，最终约 110 MB，只含 A/B raw（584/592 条）；后续播放不再
写源 bag 目录。缓存从首个 raw 开始，所以两份播放器的进度不能当作同步证据。

最初向量 topic 使用 Best Effort 时，大消息分片丢失使实收频率偏低；改用 reliable/depth 2
和 Fast DDS 异步发布。修复 Shell 后台播放器忽略 SIGINT 导致退出残留的问题，清理改用
SIGTERM。首次旧测试播放器已清理，最终验证使用单个播放器。

## 验证

- 完整自动测试 `57 passed, 1 skipped`。新增测试覆盖 32FC2 大小端、行 padding、
  带符号通道、同时间戳配对、循环回退、队列上限、画面过期和非法向量。
- `record010` 单播放器、1x、36 秒订阅检查：四路数值各收到 313–316 条，
  实收约 9.82–9.94 Hz；dashboard 收到 318 帧，约 10.00 Hz。
- 向量 shape 为 `288×384×2 float32`、全部有限、metadata 时间戳和基准哈希有效，
  检查错误 0。每侧平均重建约 31.3/31.4 ms，p95 约 33.7/33.0 ms。
- 从实际 dashboard topic 解码保存 PNG 并检查画面；配置 YAML、Shell 语法、CLI help
  和 `git diff --check` 通过。没有进行 RViz GUI 人工交互验收。
- 最终运行报告和画面位于忽略的 `local/tactile/live_replay_check_gpdhoq11/`。

## 限制

这是回放可视化验证，没有连接设备或发布控制指令。尚未加入向量 observation/replay，
没有完整 depth/delta/wrench 面板，也没有物理坐标和单位标定。可靠传输不等于完整逐帧
录制；本工具允许跳帧，未做硬实时或长时间性能验收。所有提交均为本地，没有 push。
