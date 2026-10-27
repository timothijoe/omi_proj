# CLI入口与副作用

从项目根目录运行。此页只索引入口，完整参数查对应教程或模块 `--help`，不把某次运行配置当通用默认。

本仓库使用下面的独立脚本，训练网页需另开终端启动并指向同一run。

| 目的 | 入口 | 副作用与说明 |
| --- | --- | --- |
| 只读解析配置 | prepare_bc_rl.sh / run_async_rl.sh 加 --parameter 和 --print-settings | 不启动控制或训练 |
| 新建RL任务 | scripts/prepare_bc_rl.sh | 写新run；不能覆盖已有任务 |
| 在线RL | scripts/run_async_rl.sh | --execute启动现场Actor；--enable-policy允许策略动作；独立Learner |
| 人工采集 | scripts/collect_rl_episodes.sh | execute模式控制并记录新数据 |
| 固定BC评估 | scripts/run_bc_episodes.sh | 推理/控制/录制，无Learner；--resume仅属于该入口 |
| 监控 | scripts/view_training_monitor.sh | 只读run，本机网页，不停止训练 |
| 会话归档 | scripts/training_archive.sh | 校验、打包/恢复文件；不驱动机器人 |
| 接收端 | scripts/robot_controller.sh | build写构建产物，preview离线；真机连接需显式授权参数 |
| SpacePilot | scripts/spacepilot_test.py | 默认预览，execute才发送；GUI为spacepilot_pose.sh |
| grid看板V2 | scripts/view_grid_observation_live_v2.sh | 独立图像与EEF/HUMAN/POLICY bar；只发布显示与诊断 |
| 原版grid看板 | scripts/view_grid_observation_live.sh | 保留的V1入口 |
| 传感器 | omi_sensors.cli | live连接传感器，record写bag；不启动机器人控制 |
| 仿真 | omi_hil_rl.training.sim_train | 模型、经验和日志写到指定目录，无SDK连接 |

操作导航：[教程](../../tutorials/README.md)。关键CLI默认可能与主配置不同：async batch默认2、min-demo默认1、探索std默认0；选定SpacePilot任务显式设置64、100、0.05。在线RL不存在 `--resume`。

配置解析与校验见 [run_settings.py](../../src/omi_hil_rl/hil/run_settings.py)，实际生效参数以只读打印和保存的会话配置为准。运动使能不能由JSON自动开启。
