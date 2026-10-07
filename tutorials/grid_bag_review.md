# 小矩阵触觉＋腕部ROI＋机器人：通用RViz回放

适用：包含`/omi/tactile_grid24x16/{a,b}/{deformation,shear,depth}`的MCAP包，
支持一个bag目录，或包含恰好一个bag的ZIP。不是实时传感器看板，不连接设备、不回放控制命令。

## 启动

在项目根目录，先查看帮助：

```bash
bash scripts/view_grid_observation_3d.sh --help
bash scripts/view_grid_observation_3d.sh /path/to/bag.zip
# bag目录也支持；倍速通过命名参数设置
bash scripts/view_grid_observation_3d.sh /path/to/bag_directory --rate 0.5
```

本次验证用的文件：

```bash
bash scripts/view_grid_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/grid24x16_bag_001.zip
```

首次生成10Hz图像缓存可能耗时，随后循环播放；Ctrl+C或关闭RViz可停止本次进程组。
默认仅本机domain92，同入口同domain有占用锁。需要并行时用`--domain 91`等空闲域；
不要与其他同domain回放混用。本命令不会停止原来的窗口或实时采集。

依赖：已安装ROS、RViz、robot_state_publisher；具有ROS/NumPy/Pillow/SciPy/gymnasium/PyYAML
的Python环境和marvin_msgs消息。沿用`local/robot_state/viewer.env`，模型位于
`local/models/omi_marvin_stand_axis_corrected_v1`。使用`--model-bundle PATH`可覆盖模型位置。
Python用`OMI_TACTILE_PYTHON`覆盖；重建资源见[机器迁移清单](machine_transfer_checklist.md)。
本机Jazzy已验证，Humble未验收。

## 显示与缺失值

- 外部RGB及其128 ROI；腕部使用包中128 ROI，只放大，不再裁剪。
- deformation/shear按16×24网格显示全部384个向量，保留数值单位；20显示像素/SDK单位，
  大于24显示像素的箭头截断并标红。depth固定0..0.3色标，超过范围显示饱和，不修改数据。
- 关节驱动命名修正版机器人；左EEF坐标轴使用包内姿态，模型/TCP对齐未标定。
- 缺失字段显示WAITING，raw明确显示不订阅。不能从小矩阵还原raw。
- wrench仅在包内有有效消息时显示；零条消息不伪造为零力。
- 开始缺关节数据时模型是中立占位，不能作为真实姿态；看板显示WAITING。

## 时间与诊断

默认按录包接收顺序预览，保留原header；允许header比接收时间晚，并显示FUTURE/时钟提示。
启动报告和缓存manifest记录future_headers计数及最大超前量。此预览不是训练同步，
不能把两台机器的时间差当作真实传输时延，也未自动校正时钟。

```bash
# 只准备缓存并打印消息计数/时间警告，不启动RViz
bash scripts/view_grid_observation_3d.sh /path/to/bag.zip --prepare-only
# 严格拒绝超前时间戳（旧回放器默认依然严格）
bash scripts/view_grid_observation_3d.sh /path/to/bag.zip --prepare-only --strict-clock
# 无GUI、限时检查；结束后停止本次子进程
bash scripts/view_grid_observation_3d.sh /path/to/bag.zip --no-rviz --duration 20
```

缓存和临时模型位于`local/grid_recorded_review/`，源路径/文件大小/修改时间/处理版本参与缓存标识。
不修改ZIP或原bag。仅支持MCAP及无文件压缩/文件级zstd，不适配旧完整场话题。
本版本不开发raw发布或策略订阅接口；原有回放脚本保留。
