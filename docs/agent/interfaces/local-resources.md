# 本地资源定位

完整的按功能拷贝/重装清单见[换机器教程](../../../tutorials/machine_transfer_checklist.md)。
当前OMI新原生看板无需SDK；旧看板重建需要SDK和固定基准；SDK直读采集需要厂商依赖但不需要离线基准。
`ros2_camera_clip_tools`仅为历史外部工具，不是OMI合并看板的运行依赖。
`marvin_msgs`仅在旧完整observation/关节反馈路径需要，应复制匹配源码并在目标机重建。

当前 A 臂场景通过 `--scene` 或 `OMI_TIANJI_SCENE` 定位。2026-10-01 已从本机已有的 `cooking_proj` 资源恢复完整 `robot_assets` 和相邻 `MarvinCCS` 到 `omi_proj/local/assets/`，其中包含灵巧手模型。`source scripts/env.sh` 默认使用项目内的 `local/assets/robot_assets/mujoco/right_chopping_scene.xml`；可在激活前设置 `OMI_TIANJI_SCENE` 覆盖。来源路径与场景 SHA256 保存在忽略版本控制的 `local/assets/provenance.json`。换机器时按 [manifest](../../../manifests/resources.yaml)恢复资源。

模型资源、pip 缓存放在由 `.gitignore` 排除的 `local/`；生成文件写在 `data/`，虚拟环境在 `.venv/`，同样被忽略。已选的一张验证 PNG 和一段小 GIF 放在 `docs/evidence/` 作为可审阅证据。恢复过程复制已有资源，来源文件保留。`OMI_TIANJI_SDK_ROOT` 默认指向兄弟目录 `TJ_FX_ROBOT_CONTRL_SDK`；它表示包含 `SDK_PYTHON` 的目录，供将来显式配置 `TianjiConfig.sdk_root`，仿真不会加载或连接 SDK。

工作区同级的 `ros2_camera_clip_tools/` 是相机 ROI/RViz 辅助工具；输入 rosbag 当前位于
`/home/zhoutong/Downloads/img/record010/bag_001`，静态预览位于同级
`camera_roi_preview/`。它们都不在 `omi_proj/` Git 仓库内，路径、用途和恢复说明登记在
[资源 manifest](../../../manifests/resources.yaml)，跨目录入口统一由[工作区总索引](../../../../README.md)维护。

辅助工具保留原始单进程 `view_camera_clip_original.sh`，以及带 `observation`、`512`、
`both` 三种模式的 `view_camera_clip.sh`。后两种放大相关模式由独立进程订阅 128 clip；
生成 topic 只用于 RViz，不是 OMI observation 的依赖。
