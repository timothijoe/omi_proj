# 排障、停止与恢复

| 现象 | 检查和处理 |
| --- | --- |
| `Tianji MJCF does not exist` | 核对 `--scene` 指向 XML 文件，而非目录；恢复完整 `robot_assets` 与 `MarvinCCS` 相对资源树。 |
| MuJoCo 报 mesh 或灵巧手文件缺失 | 仅有 XML 不够；按 [资源清单](../manifests/resources.yaml) 恢复依赖。 |
| EGL 渲染失败 | 确认 MuJoCo 可用离屏后端；可先只运行 `sim.preflight` 与 `sim_eval`，它们不需要渲染。 |
| `No module named ...` | 在 `omi_proj/` 重建 `.venv` 并按 [环境教程](environment_setup.md)安装对应 extra。 |
| JSONL 校验失败 | 检查是否空文件、回合连续性和动作来源；不要手改一行后直接用于训练。 |
| 示范导入模型不匹配 | 确认录制和训练使用同一 A 臂任务与场景。 |
| 仿真训练想停止 | `Ctrl+C`；重新训练时换输出目录，避免把旧结果当作完整检查点。 |

设备错误、反馈停滞或意外运动不属于仿真排障；停止实验并交由现场人员处理，不自动重试运动。
