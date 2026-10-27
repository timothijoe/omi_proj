# OMI：天机机械臂 Human-in-the-Loop RL

本项目面向天机Marvin A臂（左臂），提供多模态采集、示范BC、人工接管的异步SAC在线训练与ROS控制接收端，另有MuJoCo仿真验证路径。已有真机运行记录；自主策略效果与控制性能需要分别验收。

先读[文档入口](docs/README.md) → [当前摘要](docs/current.md)，再按任务选择模块和教程。历史资料按模块归档，不作为默认操作依据。

| 目的 | 入口 |
| --- | --- |
| 当前训练配置与正确run | [SpacePilot BC6148运行／续跑](tutorials/spacepilot_bc6148_online_rl.md) |
| 相机、触觉、末端与指令实时查看 | [RViz V2](tutorials/grid_live_review_v2.md) |
| 训练与经验池状态 | [训练网页](tutorials/training_monitor.md) |
| 新鲜度门控与统一健康监控待办 | [设计与验收](docs/design/system-health-monitoring.md) |
| 仿真／环境／迁移 | [教程导航](tutorials/README.md) |
| 开发与文档维护 | [AGENTS.md](AGENTS.md)、[维护规则](docs/design/documentation-system.md) |

运行使用本仓库`scripts/`下的独立入口；参数和任务目录需显式核对。
Git不包含全部SDK、模型、bag和运行环境，见[换机清单](tutorials/machine_transfer_checklist.md)。统一术语见[CONTEXT.md](CONTEXT.md)。
