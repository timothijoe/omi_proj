# 2026-10-02：相机和触觉合并显示

## 目标与实现

用户要求先 commit 保存当前版，再将相机 observation 风格的原图与 128 像素裁剪图加入
触觉可视化。修改前工作区干净，创建检查点提交 `64d62f2`，文件内容与 `cfe1081` 相同。

新增 `view_observation_bag.sh`、RViz 配置及 `camera_panels`；原图预览带 ROI 框并保持
宽高比，128×128 裁剪在合成图中按原尺寸显示。ROI 边界复用 observation 几何，
Lanczos 缩放沿用既有人用相机工具。右侧保留完整 A/B raw/deformation/shear 面板。

合并模式只启动一个播放器，四路 topic 从同一缓存回放。新增缓存键包含 topic 白名单，
旧纯触觉缓存保留。record010 新缓存约 2.6 GiB，含头部 829、腕部 298、A raw 584、
B raw 592 条，无控制 topic。源 bag 目录不写入。

## 验证

- 自动测试 `59 passed, 1 skipped`；新增头部/腕部 ROI 边界、Lanczos 数值、128 像素
  原样贴入、缺失与过期显示检查。
- record010 1x 实际回放，36 秒订阅：合成 dashboard 357 帧，约 9.94 Hz；四路向量场
  约 9.42–9.59 Hz。每侧平均计算约 33.2 ms，数值检查错误 0。
- 从 `/omi/observation/dashboard` 解码得到 `1792×740 rgb8`，检查实际 PNG：
  两路相机原图、绿色 ROI、128 小图与 A/B 触觉均正常出现，时间戳和新鲜度独立显示。
- 本地结果在 `local/tactile/live_replay_check_idra703n/`，缓存和生成物均被 Git 忽略。
- Shell 语法、RViz YAML、本地 Markdown 目标和 `git diff --check` 核查通过。

## 边界

单播放器保证播放进度一致，不保证不同传感器时间戳相同；触觉重建也有计算延迟。
相机图仍是人用 Lanczos 预览，与策略最近邻图像不同。没有改动 observation 张量或训练。
未做 RViz GUI 人工交互验收或真机连接；没有 push。当前机制见
[实时可视化纪传体](../evolution/tactile-live.md#相机与触觉合并模式)。
