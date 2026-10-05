# 实时 policy、RB 接管与 SDK 输出

动作限幅的实现与后续建议见[动作缩放策略](../docs/agent/training/evolution/policy-action-scaling.md)：当前代码分别限幅，统一缩放尚未实施。

入口 `scripts/run_policy_gamepad.sh` 读取真实观测，运行无关节 GPU 模型，再由手柄节点选择动作。默认仅预览；远端接收程序由用户确认选择左臂、`FRAME_BASE=0`，本机不调用 SDK。

## 运行

在项目根目录运行，输出目录必须不存在：

```bash
bash scripts/run_policy_gamepad.sh \
  --checkpoint local/eef_history/oct04_nojoints_cuda_run1/best.pt \
  --output local/policy_gamepad/my_preview \
  --eef-reference bag-baseline-v1 --policy-scale 0.1 \
  --duration 60 --device cuda
```

预览使用独立候选话题，仲裁器不创建机器人命令发布者。需要发送真机动作时，使用新输出目录并加 `--execute`；该参数会直接启动发布，没有额外回车确认。默认 domain 13，修改用 `OMI_POLICY_DOMAIN_ID`。手柄默认 `/dev/input/js0`，可用 `--gamepad` 指定。

- RB（右侧上方肩键，按钮311，不是下方RT扳机）按住：人工接管；摇杆居中时也是人工零动作。用户已确认继续使用此键。
- RB 松开：丢弃接管期间的旧候选，等待松开之后的新 policy 候选。
- 手柄断开、候选缺失或过期：零动作。候选只消费一次，不重复最后一条。
- Ctrl+C 或模型进程退出：联动停止；独占输出时仲裁器尝试发送最后一条零增量。

这是发送增量的控制语义；远端 SDK 的运动停止行为仍由接收程序实现。

## 坐标与单位：只在最终出口转换一次

训练 GT 为 `dp = p_future - p_current`、`dr = Log(R_future R_current.T)`，基坐标系表达，约100 ms步长，单位 m/rad。模型输出先用 checkpoint 的统计量反归一化，再乘显式 `--policy-scale`（默认1）。候选 `TwistStamped` 的 frame 是 `base_link`，字段表示每步增量，**不是速度**。

候选进入 RB 仲裁后，人工与 policy 都调用和 `scripts/gamepad_test.py` 相同的 `sdk-x-forward-z-left` wrapper：

1. 平移和旋转向量换轴 `(x,y,z) -> (x,-z,y)`。
2. 旋转向量转旋转矩阵，再转 SDK ABC，满足 `R = Rz(C) Ry(B) Rx(A)`。
3. 输出 mm/度；模型动作发布 `/omi/action/decision`，手动接管和 RB+X 返回发布
   `/omi/action/manual_decision`（均为 `Float64MultiArray`，空 layout）。
   接收端触觉保护默认关闭，显式开启后只拦截模型，手动通道不受影响。

不是直接交换欧拉角，也不能在远端重复这个转换。SDK `FRAME_BASE=0` 对应平移相加、姿态左乘 `R_target = R_delta R_current`；与 GT 定义一致。源证据为本机 `Downloads/oct04/sdk_python/SDK_PYTHON.zip` 内 `fx_tcp_force.py` 与 `docs_1003_delta_IK.md`。

本转换仍以指定安装方向、SDK UserFrame 对齐，以及训练 EEF 与 SDK TCP 是同一物理点为前提。GT 数学核对不等于现场 TCP 标定；如果实时 EEF 本身不是训练使用的 base_link 轴定义，仅在输出端换轴无法修正输入。

## 实时 EEF 基准补偿 v1

必须显式选择 `--eef-reference raw` 或 `bag-baseline-v1`。后者仅给模型观测位置加 `[-0.062159,-0.171229,+0.000024] m`，不改变原始 ROS topic，也不改四元数。原有独立 shadow 默认仍是 raw。

此补偿从 RViz 临时基准扩展到模型输入，是显式选择。固定基坐标系平移在 GT 位姿差分中抵消，**不能每个动作再加一次**。若实际差异是末端局部 TCP 偏移，旋转会产生额外位移，不能用这个常量代替完整几何标定。

## 限幅和记录

默认10 Hz、10 mm/s及10°/s，即每步平移范数不超过1 mm、旋转向量范数不超过1°。先乘显式 policy-scale，再分别按平移向量/旋转向量的范数等比例限幅。超出执行上限就压到上限，保持平移方向/旋转轴；未超限不放大。不是逐轴截断，也不是直接裁剪SDK ABC角。平移和旋转独立缩放，因此两者相对比例可能改变。未缩放预测的实验异常边界仍保留（50 mm、0.25 rad≈14.32°），超过该边界仍拒绝。候选还要求 strict 时间戳、完整10帧、有限输出及100 ms有效期。诊断时间模式不允许发布候选。

`session.json` 保存启动参数；`policy/predictions.jsonl` 保存网络原始 m/rad、policy_scale后限幅前值、限幅后的候选、平移/旋转限幅比例、转换预览、输入与门控；`selected_actions.jsonl` 保存实际被选中的来源、原始 mm/旋转向量度、转换后 mm/ABC度、RB状态和 published。选中候选的 reference 时间戳可关联预测日志（浮点时间舍入允许亚微秒差异）。终端也显示原始值、转换模式和最终值。

## 已验证及边界

2026-10-04：90项相关测试通过，1525条真实训练/验证GT的 SDK 变换重建核对通过。30秒现场预览完成280次GPU推理，234条候选均被仲裁器选择；P95推理14.24 ms。该次使用补偿和0.1缩放，全部 published=false，没有机器人运动验收；RB切换由自动测试覆盖，该次现场未按RB。

scale=1 的原始输入预览因约7 mm单步输出超限，候选全部被拦截。补偿后的位姿最大标准化偏差仍约16.49（raw约30.66），说明当前输入与训练分布明显不同；不能从链路可用推断闭环任务成功。

2026-10-04后续：用户要求将执行超限改为保持方向的等比例限幅，已启用；早期预览中“超限拒绝”结果描述的是修改前版本。99项相关测试通过，包含真实大输出回放、SDK旋转角、独立限幅和RB仲裁。本次未启动真机。启动参数不变，重启进程后生效。
