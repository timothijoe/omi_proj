# 本地资源定位

末端实验数据/模型/报告位于 `local/eef_bc/`，消息包构建位于 `local/action_ros/`，均Git忽略。
需原bag和匹配Marvin消息；不需要机器人mesh或触觉SDK。新机器按
[末端教程](../../../tutorials/eef_action_space.md)重建消息包并重新导出。

Stand派生模型固定归档为 `local/models/omi_marvin_stand_axis_corrected_v1/`，包含
命名URDF、15个原STL、原URDF及来源说明。它不是厂商原版，不是已标定控制模型，
整个目录被Git忽略，换机需单独复制。网格为`package://` URI，资源包安装描述尚未实跑。
现有方向修正回放仍读取原`Marvin_Stand_2026.2.2.rar`，生成临时运行URDF及本机mesh URI，
不会自动读取固定命名归档。操作与依赖见[教程](../../../tutorials/corrected_stand_review.md)。

录包BC和影子推理使用 `local/bc/` 存NPZ、只含观测的MCAP、权重与报告，全部Git忽略。
原始bag、匹配Marvin消息需另行准备；运行环境安装bc extra和ROS系统包，不需要Daimon SDK
或机器人mesh。恢复与命令见[教程](../../../tutorials/bag_bc_shadow.md)和[manifest](../../../manifests/resources.yaml)。

完整的按功能拷贝/重装清单见[换机器教程](../../../tutorials/machine_transfer_checklist.md)。
当前OMI新原生看板无需SDK；旧看板重建需要SDK和固定基准；SDK直读采集需要厂商依赖但不需要离线基准。
`ros2_camera_clip_tools`仅为历史外部工具，不是OMI合并看板的运行依赖。
`marvin_msgs`在完整observation、机器人回放及新外部录包原生字段+3D看板路径需要，
应复制匹配源码并在目标机重建；纯schema2 SDK传感器看板不需要。

新外部录包看板使用命令参数指定ZIP/目录，不依赖原机器Downloads布局。
`local/recorded_review`存生成显示缓存；`local/robot_state/models`存本机生成URDF，
`local/robot_state/viewer.env`存本机Marvin overlay等可信Shell配置，均不进Git。
输入包、模型资产和匹配消息定义另行恢复，见[资源清单](../../../manifests/resources.yaml)
及[拷贝清单](../../../tutorials/machine_transfer_checklist.md)。缓存不是训练数据集。

当前 A 臂场景通过 `--scene` 或 `OMI_TIANJI_SCENE` 定位。2026-10-01 已从本机已有的 `cooking_proj` 资源恢复完整 `robot_assets` 和相邻 `MarvinCCS` 到 `omi_proj/local/assets/`，其中包含灵巧手模型。`source scripts/env.sh` 默认使用项目内的 `local/assets/robot_assets/mujoco/right_chopping_scene.xml`；可在激活前设置 `OMI_TIANJI_SCENE` 覆盖。来源路径与场景 SHA256 保存在忽略版本控制的 `local/assets/provenance.json`。换机器时按 [manifest](../../../manifests/resources.yaml)恢复资源。

模型资源、pip 缓存放在由 `.gitignore` 排除的 `local/`；生成文件写在 `data/`，虚拟环境在 `.venv/`，同样被忽略。已选的一张验证 PNG 和一段小 GIF 放在 `docs/evidence/` 作为可审阅证据。恢复过程复制已有资源，来源文件保留。`OMI_TIANJI_SDK_ROOT` 默认指向兄弟目录 `TJ_FX_ROBOT_CONTRL_SDK`；它表示包含 `SDK_PYTHON` 的目录，供将来显式配置 `TianjiConfig.sdk_root`，仿真不会加载或连接 SDK。

工作区同级的 `ros2_camera_clip_tools/` 是相机 ROI/RViz 辅助工具；输入 rosbag 当前位于
`/home/zhoutong/Downloads/img/record010/bag_001`，静态预览位于同级
`camera_roi_preview/`。它们都不在 `omi_proj/` Git 仓库内，路径、用途和恢复说明登记在
[资源 manifest](../../../manifests/resources.yaml)，跨目录入口统一由[工作区总索引](../../../../README.md)维护。

辅助工具保留原始单进程 `view_camera_clip_original.sh`，以及带 `observation`、`512`、
`both` 三种模式的 `view_camera_clip.sh`。后两种放大相关模式由独立进程订阅 128 clip；
生成 topic 只用于 RViz，不是 OMI observation 的依赖。
