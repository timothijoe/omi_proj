# CLI 入口

以下均是 `python -m` 模块入口，不是安装后自动生成的可执行命令，也不是 Shell 脚本。路径相对 `omi_proj/` 工作目录解析。

| 模块 | 必要参数 | 作用 | 副作用 |
| --- | --- | --- | --- |
| `omi_hil_rl.sim.preflight` | `--scene PATH` | 编译场景并报告 A 臂任务 | 可选 `--output` 写 JSON |
| `omi_hil_rl.sim.keyboard_teleop` | `--scene PATH` | 终端逐关节点动 | `--output` 写/覆盖 JSONL |
| `omi_hil_rl.sim.interactive_rollout` | `CHECKPOINT --scene PATH` | 运行策略并允许逐步键盘覆盖 | `--output` 写/覆盖 JSONL |
| `omi_hil_rl.training.sim_train` | 无；A 臂需 `--scene PATH` | SAC 仿真训练 | `--output-dir` 写模型、回放、日志 |
| `omi_hil_rl.training.validate_recording` | `RECORDING` | 校验 JSONL | 只读 |
| `omi_hil_rl.training.sim_eval` | `CHECKPOINT`；A 臂需 `--scene PATH` | 无接管评估 | 只读模型、运行仿真 |
| `omi_hil_rl.sim.visualize` | `--scene PATH` | 教师或 `--checkpoint` 策略渲染 | `--output-dir` 写 PNG/GIF/JSON |
| `omi_hil_rl.training.plot_progress` | `PROGRESS OUTPUT` | 绘制固定种子评估曲线 | 写 PNG |
| `omi_hil_rl.sim.smoke` | 无 | 代理模型快速回合 | 控制台输出 |

训练可附加 `--demo-recording PATH` 导入真人格式的示范；默认不导入。每个模块的完整参数以 `python -m <模块> --help` 为准。没有真机 CLI；不要把仿真命令指向 SDK 控制器。
