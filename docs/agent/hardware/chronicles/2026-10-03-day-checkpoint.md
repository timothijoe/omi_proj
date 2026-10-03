# 2026-10-03：阶段性版本检查点

用户要求将当天累积的代码、配置和文档保存为可回退本地版本。本次包含机器人模型回放对照、
EEF动作/BC影子流程、实时腕部相机与ROI传输、触觉24×16数值场、wrench SDK格式修复、
可选raw/wrench发布、通用grid录包可视化，以及三件套操作教程。
这是开发检查点，不是完成真实机器人控制或全部硬件性能验收的稳定发布。

提交前检查：项目venv全套测试200通过、11跳过；SDK/ROS环境补跑grid回放、
触觉网格、SDK适配、传输与旧看板相关测试69通过。git diff --check通过，
暂存范围不包含bag、SDK、模型、截图、权重或日志。logs_pc_flux新增忽略规则，文件未删除。

## 当前约定

- 独立tactile默认deformation/shear/depth的高16宽24数值场；raw和wrench显式开启。
- raw仍为`/omi/tactile/{a,b}/raw`；网格数值及wrench为`/omi/tactile_grid24x16/{a,b}/...`。
- SDK无帧号wrench以主机读取时间发布，metadata明确未验证同帧、新鲜度、单位及轴。
- grid录包使用`view_grid_observation_3d.sh ZIP_OR_BAG`；raw发布已实现，grid看板raw显示尚未适配。
- 不把SDK、bag、模型网格、训练权重、日志和缓存加入Git；本地资源恢复见manifest和迁移教程。

## 回放时间基准与未完成项

回放按录包接收时间推进，每100ms取各topic最新到达样本；header仅保留用于年龄和FUTURE/STALE提示。
它重现到达顺序，并不是视觉/触觉/机器人真实采样时刻的严格同步，也不是训练对齐结果。
oct3_011触觉接收减header中位数约-22ms，腕部约-14ms；oct3_022触觉最大超前约29ms，
腕部约22ms。提示时钟或时间戳基准不一致，不能解释成负时延或精确校正量。
触觉header在SDK读取后生成，腕部header是主机收到完整JPEG的时刻；两者均非曝光/采样时间。
各链路前置处理与传输延迟可能不同且波动，接收同时不等于采样同时。

待完成：跨机时钟/相对延迟验证、远端wrench录包复验、raw组合真机及看板显示、
grid实时看板/策略订阅适配、持续吞吐和Humble验收。URDF基座/TCP/限位仍未完成标定，不能用于控制。

常用操作入口：[速查](../../../../tutorials/sensor_commands.md)、
[腕部](../../../../tutorials/wrist_camera.md)、[触觉](../../../../tutorials/tactile_grid_transport.md)。
只创建本地commit，不push，不停止当前实时采集。
