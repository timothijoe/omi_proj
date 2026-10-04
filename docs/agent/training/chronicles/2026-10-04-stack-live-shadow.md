# 2026-10-04：无关节模型实时影子推理入口与现场阻塞

## 任务与结果

用户要求检查当前输入能否运行模型，并先做影子模式读取现场 ROS 数据尝试 inference。
已新增独立入口，成功加载无关节模型到 CUDA，验证与离线计算一致；实际现场试跑尚未产生预测，原因是 EEF 时间戳检查失败，随后 EEF 发布中断。
**不能把模型加载/离线计算通过表述为当前实时输入已经跑通。**

## 实现

- `src/omi_hil_rl/training/stack_shadow.py`：订阅现场输入、按接收时间组织固定10槽历史、GPU推理、写本地状态与报告。
- `scripts/run_stack_shadow.sh`：默认domain13，ROS Jazzy与独立CUDA环境；不加载关节消息包。
- `tests/test_stack_shadow.py`：缺失/过期/未来header、错误frame、时间回退、历史缺帧和诊断模式检查。
- [操作教程](../../../../tutorials/stack_shadow.md)：完整输入、命令、模式和输出解释。

使用 `local/eef_history/oct04_nojoints_cuda_run1/best.pt`，版本
`eef-current9stack-no-joints-v1`，best step1300，CUDA FP32。
实际使用双相机、双指三场、EEF xyz/xyzw，不订阅关节；q7与joint_mask保持禁用。
当前+过去9时刻间隔100ms，缺失槽位不压缩；复用训练ROI/颜色处理、场通道顺序、四元数处理和checkpoint归一化。
checkpoint的wrist配置为optional，以camera_mask记录实际使用情况。

只写预测文件，不创建任何动作发布者、不调用执行器。`execution_allowed`始终为false。
保留RViz版本与已发现的L7—EEF关系未对齐问题，不把L7坐标替代模型输入的ROS EEF。

## 验证

- `tests/test_stack_shadow.py`、`tests/test_eef_stack.py`、`tests/test_eef_history_online.py`：19项通过。
- GPU加载成功：PyTorch2.14.0+cu130、CUDA可用。
- 从原验证集取真实完整窗口及人为带历史缺槽的窗口；影子forward_windows与原离线模型forward计算出的反归一化动作最大差均为0。
- 上述GPU一致性验证使用已有验证集输入，不是现场实时推理成功的证据。

## 现场试跑证据

所有路径相对项目根，均为本机local产物：

| 运行 | 模式/时长 | 结果 |
| --- | --- | --- |
| `local/stack_shadow/oct04_live_run1/` | strict，30秒 | 300次决策，0次推理；EEF收到868条，仅5条通过入口检查，859条header超前、4条header过旧；决策时未形成完整当前输入 |
| `local/stack_shadow/oct04_live_diagnostic1/` | receive-only-diagnostic，30秒 | 300次决策，0次推理；完全没有收到EEF，相机及触觉正常 |
| `local/stack_shadow/oct04_live_diagnostic2/` | receive-only-diagnostic，60秒 | 600次决策，0次推理；完全没有收到EEF；外部RGB1307条、腕部1798条，双指每场约1664–1665条 |

结束时再次检查 `/tj/info/eef_left`：Publisher count为0，现有RViz也显示STALE。
这只能说明本次时段的发布状态；此前该话题约50Hz可用的记录仍有效。

strict模式保留原训练入口的源header年龄阈值：EEF50ms、其他250ms、允许超前100ms。
诊断模式显式跳过源header年龄检查，但仍要求接收年龄、形状、有限值、四元数和frame正确；
日志注明`training_header_guards_enforced=false`。没有伪造缺失EEF或使用已过期位姿补齐推理。
两轮诊断都因实际没有EEF而停止推理，未通过放宽检查制造“成功”结果。

本次没有现场动作预测与延迟统计，也没有first_window.npz；report中的相关耗时为null。
现有报告不能用于评价策略效果、模型闭环控制或实时10Hz性能。

## 继续方式

恢复左臂EEF发布，并检查发布机/接收机时钟差与header生成方式，然后优先重跑strict模式：

```bash
bash scripts/run_stack_shadow.sh \
  --checkpoint local/eef_history/oct04_nojoints_cuda_run1/best.pt \
  --output local/stack_shadow/next_strict_run \
  --duration 60 --device cuda
```

先确认有实际推理、完整历史窗口、相机mask、有限输出与deadline统计，再检查现场EEF相对训练分布的偏移。
末端基座/TCP语义仍需独立核对；本入口始终只做影子计算。
