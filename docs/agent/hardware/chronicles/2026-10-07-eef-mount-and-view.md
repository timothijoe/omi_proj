# 2026-10-07：左臂 EEF 安装平移修正与实时显示补偿移除

## 修改

用户指定左臂 A 的固定安装平移由 `(0, 0.2005, 1.121) m` 改为
`(0, 0.0260, 1.121) m`，旋转 `Rx(-90°)` 不变。接收端的 `_root_mount_matrix()`
以及可选发布的 `base_link -> Base_L` 静态 TF 均使用新值；右臂 B 未改。
新值的左臂 Y 是指定修正值，不能再称为直接取自原 Stand URDF 的 J1 Y 原点。

`/tj/info/eef_left` 仍从当前七关节反馈经标定后 SDK FK 得到 TCP 位姿，
将 SDK Base 下的毫米平移转为米，再左乘固定安装矩阵，输出 `base_link` 下的
`PoseStamped`。在关节反馈和 TCP 标定相同时，本次修改使其 Y 减少 `0.1745 m`；
X、Z、姿态不因安装平移改动。`publish_root_tf=none` 不会关闭该矩阵复合。

实时 `grid_live_review` 的 corrected 模型显示移除了旧的
`(-0.062159, -0.171229, +0.000024) m` 固定 EEF 平移及
`--eef-offset-base-m` 参数。品红色 EEF 标记、坐标轴、L7 连线及
`model_status.json` 的 `display.eef` 均直接使用原始 EEF 位姿；不再生成
`eef_display_config.json`。历史 bag 数据未改。策略观测的
`bag-baseline-v1` 显式选项仍保留旧平移，运行新发布端时需按策略契约选择 `raw`，
避免再次叠加旧补偿。

## 验证与生效边界

Python AST 语法检查、`git diff --check` 通过；直接检查左臂安装矩阵的 Y 为
`0.026`。使用项目虚拟环境及系统 ROS 路径运行相关测试：7 通过、1 跳过；
跳过项需要当前测试环境缺少的 `marvin_msgs`。未在本次修改后连接机械臂或重跑
现场 RViz，因此新坐标与实体 TCP 的多姿态一致性尚未验证。

接收端需要重建并重启，看板也需要重启才能加载新代码。
操作见[控制端教程](../../../../tutorials/robot_controller.md#左臂-eef-安装变换修正2026-10-07)
和[实时看板教程](../../../../tutorials/grid_live_review.md#实时-eef-显示坐标2026-10-07)。
