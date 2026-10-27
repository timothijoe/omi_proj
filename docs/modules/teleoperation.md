# SpacePilot与手柄人工输入

职责：读取人工轴和按键，生成候选动作/事件，由Actor仲裁后统一发布。实现见 [operator_input.py](../../src/omi_hil_rl/real/operator_input.py)。默认仍为gamepad，显式 `--input-device spacepilot` 切换；不并行启动另一个遥操作发布者。

## 三种入口必须区分

- `spacepilot_pose.sh`仅操控GUI虚拟物体，不发布机器人动作。
- `spacepilot_test.py`为独立机器人增量工具，预览与execute分离，默认实体3（ID19）按住启用。
- BC/RL的SpacePilot由Actor接入，使用HIL按键profile。Menu接管，松开在纯人工采集中归零、在线RL中归还策略；不是总停机。

## HIL输入与按键

当前预设为 [spacepilot_hil_oct17.json](../../configs/spacepilot_hil_oct17.json)，实际运行profile由主配置指向local文件，换设备需核对ID。

| 功能 | 10月17日确认的实体ID |
| --- | --- |
| Menu接管 / 数字1开始 | 0 / 12 |
| ALT成功 / Ctrl普通结束 | 23 / 25 |
| 回合外home | 26 |
| 夹爪闭合 / 张开 | 28 / 27 |
| 跟随切换 / 保存关系 | 8 / 2（当前Marker关闭，不执行） |

HIL当前review=auto，夹爪无需按住Menu，按键不用于人工保留/丢弃。数字3总开关尚未实现。原手柄继续使用RB接管、Start开始等逻辑码，见 [输入契约](../interfaces/spacepilot.md)。

## 方向、速度与调度

设备前+X、左+Y、上+Z；SDK出口转换见 [控制](control.md)。standalone速度基准10mm/s、10°/s，主配置倍率1.5/0.3对应合速度上限15mm/s和3°/s。session方案沿用已保存HIL动作范围，禁止悄悄扩大旧模型范围。

共享MotionSchedule支持首个非零/归零边沿立即发送、连续10Hz、不补发积压。它用于纯人工periodic采集、immediate人工接管及回合外调整；after-inference仍等待推理完成，不可宣称所有入口都有即时人工响应。

150ms输入过期归零人工候选；断连或250ms轮询停顿进入断连处理。启动/重连按住的键要释放后再触发。快速边沿对应训练数据要求观测递增、实际指令间隔80–150ms且无中途外部停止，不合格片段仅审计并分段。

操作见 [HIL配置](../../tutorials/spacepilot_hil.md)、[独立控制](../../tutorials/spacepilot_control.md)、[手柄](../../tutorials/gamepad_control.md)、[虚拟物体](../../tutorials/spacepilot_pose.md)。已有真实采集与输入验证；底层停止拖尾和完整逐轴现场验收不能由软件映射测试替代。

开发历史（按需）：[人工输入归档](../archive/teleoperation/README.md)。
