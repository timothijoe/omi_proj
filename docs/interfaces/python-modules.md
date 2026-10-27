# Python实现边界

| 职责 | 代码入口 |
| --- | --- |
| 异步Actor与子进程 | [hil/async_training.py](../../src/omi_hil_rl/hil/async_training.py) |
| Learner与预算 | [hil/learner.py](../../src/omi_hil_rl/hil/learner.py) |
| SAC与编码器 | [hil/networks.py](../../src/omi_hil_rl/hil/networks.py) |
| 观测/动作契约 | [hil/config.py](../../src/omi_hil_rl/hil/config.py) |
| 周期仲裁与审计 | [hil/periodic_control.py](../../src/omi_hil_rl/hil/periodic_control.py)、[periodic_replay.py](../../src/omi_hil_rl/hil/periodic_replay.py) |
| ROS输入输出 | [hil/ros_transport.py](../../src/omi_hil_rl/hil/ros_transport.py) |
| 人工输入 | [real/operator_input.py](../../src/omi_hil_rl/real/operator_input.py) |
| 历史视觉编码 | [training/eef_bc_stack.py](../../src/omi_hil_rl/training/eef_bc_stack.py) |
| 双池缓存 | [training/cached_replay.py](../../src/omi_hil_rl/training/cached_replay.py) |
| 单帧共享存储 | [hil/observation_storage.py](../../src/omi_hil_rl/hil/observation_storage.py) |
| 配置入口 | [hil/run_settings.py](../../src/omi_hil_rl/hil/run_settings.py) |
| RViz V2进程与订阅 | [real/grid_live_v2.py](../../src/omi_hil_rl/real/grid_live_v2.py) |
| 图像转换与接收诊断 | [real/grid_live_v2_core.py](../../src/omi_hil_rl/real/grid_live_v2_core.py) |
| EEF／人工／策略显示 | [real/grid_live_v2_control.py](../../src/omi_hil_rl/real/grid_live_v2_control.py) |
| 训练遥测与网页 | [hil/telemetry.py](../../src/omi_hil_rl/hil/telemetry.py)、[training_monitor.py](../../src/omi_hil_rl/hil/training_monitor.py) |
| 真机接收端 | [delta_ctrl_node.py](../../ros2/arm_delta_cmd/arm_delta_cmd/delta_ctrl_node.py) |
| 仿真 | [sim/tianji_a_reach.py](../../src/omi_hil_rl/sim/tianji_a_reach.py) |

训练不直接调用厂商SDK，硬件执行通过接收端；早期TianjiSdkArm与该ROS接收端是不同路径。各模块的行为和验收见 [模块导航](../README.md)。这些是仓库实现入口，不承诺为稳定外部API。
