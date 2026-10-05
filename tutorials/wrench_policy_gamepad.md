# 带六维力/力矩的 BC 模型：预览与真机手柄接管

当前简明操作入口见[无wrench推理与录制教程](no_wrench_policy_record.md)，
完整实验与诊断见[阶段记录](../docs/agent/training/chronicles/2026-10-05-policy-input-audit-no-wrench.md)。

## 不使用六维wrench的对照模型

用户要求关闭六维力/力矩输入。训练入口新增`--without-wrench`，重新建立不含wrench编码器/融合层的模型，
不是把旧模型输入填零或修改推理mask。仍使用双相机、双侧触觉网格、EEF、10帧历史；触觉网格没有关闭。
数据沿用排除第三包后的341训练/161验证，训练1000步、batch32、lr0.0003、seed7。
输出`local/passive_bc_20261005_no_wrench_no_third_train_v1/`。
归档数据契约保留原始wrench用于溯源；检查点recipe中的`observation_inputs`才是本轮实际网络输入，
`ablation=without_wrench_retrained`、`wrench_history=false`，不含wrench归一化参数。
实时入口从检查点识别该变体，不订阅wrench、不检查wrench历史；其余有效性检查保持不变。

录制预览命令：

```bash
bash scripts/run_no_wrench_policy_record.sh \
  --output local/policy_gamepad/no_wrench_record_01 \
  --duration 3600
```

沿用用户上轮指定的训练集最佳选择：默认本轮第1000步`actor_train_best.pt`，保留Ctrl+C写完录制的流程；`--execute`才发送真机动作。
本轮自动验证选择仍停在第0步，`actor.pt`不是完成BC更新的模型，不拿它作本轮测试入口。
第1000步训练MSE=0.000583、验证MSE=0.131478；仍存在明显泛化差距。
将`record_train_best_01`的215个完整现场窗口离线重放：不提供任何wrench字段也能推理，
X预测仍全部为负，范围约-0.445至-0.127mm/步，中位数-0.434mm/步。
原带wrench模型在相同窗口的中位数约-0.499mm/步；去掉wrench减轻部分幅度，但未解决后退。
这些窗口来自旧模型的实际轨迹，不代表新模型的闭环轨迹；不据此声称真机成功或安全。
新模型没有自动取代旧入口默认检查点。移除wrench不代表已经解决方向问题，先检查离线重放与预览。

## 推理时连续保存观测，Ctrl+C收尾

使用新入口（默认仍为预览，不发机器人动作）：

```bash
bash scripts/run_wrench_policy_record.sh \
  --checkpoint local/passive_bc_20261005_wrench_no_third_train_v1/actor_train_best.pt \
  --output local/policy_gamepad/record_train_best_01 \
  --duration 3600
```

确认接管和运行条件后，换新的输出目录并显式加`--execute`才发真机动作。
`--checkpoint`可选择原模型；不指定则继承wrench入口的原第200步模型。
录制不会改善模型，训练集最佳模型依然有过拟合和方向不可靠风险。

每次完成推理保存`policy/observations/<reference_ns>_<epoch>.npz`，含归一化前的
双相机、触觉网格、EEF、wrench完整10槽数组、history/camera/wrench masks、未缩放m/rad模型输出，
以及该次预测的状态、输入时效、候选门控与发布状态metadata。被门控拦截但完成推理的窗口也保存。
没有有效窗口、未完成推理的时刻不伪造观测，原因保留在`policy/predictions.jsonl`。
归一化参数、模型路径/哈希在`policy/manifest.json`。这是网络实际输入的裁剪/缩小后图像，不是原始全分辨率视频。
最终动作与RB状态在`selected_actions.jsonl`，用`selected_policy_reference_ns`对应观测`reference_ns`；
RB人工期间没有被选中的模型候选也可独立分析。完整复现还需保留对应checkpoint。

后台单线程压缩写盘，待写队列上限16个窗口；满队列丢弃并在预测日志/终端报告，不等待磁盘。
默认压缩文件容量上限10GiB，可用`--record-max-gb 20`调整；到上限/磁盘失败会停止保存新窗口，
控制继续运行并报告错误。总结`complete=false`不可当作完整记录。

按Ctrl+C后不再产生新候选，启动器通知仲裁器停止（独占时尝试发送最终零动作），
录制线程写完已入队窗口，再生成`policy/observations/summary.json`（saved/dropped/errors/flushed）。
每个窗口先写`.partial`、flush/fsync，再原子改名，部分文件不当作完整窗口。
终端出现“观测保存结果”后退出；连续Ctrl+C不会中断这段收尾。
启动器给录制60秒收尾时间，磁盘永久卡死会强制退出；SIGKILL、断电或磁盘故障无法保证全部保存。
这是软件停止流程，不代替硬件急停。

模型为 `local/passive_bc_20261005_wrench_train_v1/actor.pt`（最佳第200步）。
这是记录指令的离线 BC，不是在线 RL；尚未验证真机插入成功率。
新入口复用原来的独立手柄仲裁进程，默认预览，不发送机器人命令。

## 1. 先预览

在项目根目录，保持双相机、双侧触觉网格/wrench、EEF 发布程序运行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/run_wrench_policy_gamepad.sh \
  --output local/policy_gamepad/wrench_preview_01 \
  --duration 60
```

输出目录必须尚不存在；再次运行换成 `_02` 等。默认 domain 13、CUDA、手柄 `/dev/input/js0`。
可用 `--gamepad /dev/input/js1` 修改设备；`OMI_POLICY_DOMAIN_ID` 修改 domain。
预览与执行的候选话题隔离，预览不会创建两个最终动作话题的发布者。
不要在预览时另开手柄直控程序；否则那个独立程序仍然可能使机器人运动。

查看终端和输出目录：

- `policy/status.json`：`history_mask` 十槽完整、`wrench_mask` 全为1、`candidate_gate=ok`。
- `policy/predictions.jsonl`：归一化后还原出的 m/rad 动作、缩放/限幅、SDK转换预览、输入时间。
- `selected_actions.jsonl`：RB按下 `source=human`，松开后有效候选 `source=policy`，预览始终 `published=false`。
- 无输入时只会等待并记录原因；到时退出，没有推理的运行返回非零退出码。

**预览中先检查 RB 接管、松开恢复、拔掉手柄暂停，核对运动方向和输入分布，不能只看进程启动成功。**

## 2. 配置接收端的两个话题

接收端构建、SDK环境和TCP参数见[接收端启动教程](robot_gamepad_startup.md)。
模型话题固定，手动话题现在默认自动匹配接收端：

| 来源 | 接收端参数 | 话题 |
| --- | --- | --- |
| 模型 | `delta_topic` | `/omi/action/decision` |
| RB手柄、RB+X | `manual_delta_topic` | 执行时读取接收端实际配置 |

新入口默认`--manual-topic auto`。执行前只读查询`/delta_ctrl_node/get_parameters`，
并核对两个实际订阅的节点名、类型和话题；原来的`/omi/controller_test/decision`可直接自动匹配，
无需仅为改话题重启接收端。查询失败、订阅不匹配、手柄打不开或缺少所需轴/RB时拒绝启动动作发布进程。
启动终端打印选中的手动话题，`session.json`记录检查结果。
可显式指定`--manual-topic /omi/controller_test/decision`，但仍须通过与接收端的一致性检查。
预览不要求接收端，auto使用常规手动话题且不发布；因此预览本身不能证明真机订阅一致。
启动检查不是永久监控，不应在执行过程中重启或重配接收端。
停止旧直控/策略发布进程，不允许多个控制器竞争。接收端也可以使用常规配置：

```text
delta_topic:=/omi/action/decision
manual_delta_topic:=/omi/action/manual_decision
```

接收端需已启用 `connect_on_start:=true`、`motion_authorized:=true` 才能执行。
这不是只读操作：连接会初始化SDK/TCP并切换模式，必须按现场安全规程操作。
双方ROS发现设置须兼容。此脚本使用 domain 13 / SUBNET；接收端也使用相同domain和SUBNET，
若继承旧的LOCALHOST环境，应按该设置重新启动接收端。无需另开 `gamepad_test.py`。

## 3. 显式执行

确认接收端、传感器、手柄和预览检查无误，工作空间无人且硬件急停可用后：

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/run_wrench_policy_gamepad.sh \
  --output local/policy_gamepad/wrench_execute_01 \
  --duration 60 \
  --execute
```

**加 `--execute` 后没有额外确认提示；一旦输入齐全、手柄连接且RB松开，就可能执行模型动作。**
启动时按住RB、摇杆居中可保持人工零动作。默认运行60秒，结束或Ctrl+C联动停止子进程，
仲裁器尝试发送零增量。此软件行为不是安全认证的硬件急停。

## 4. 优先级与参数

外部RGB默认`--rgb-max-age-ms 500`，头时间年龄与接收后缓存年龄均单独按500ms限制。
腕部RGB和触觉仍为250ms，EEF仍为50ms，完整10槽/未来时间戳等门槛保留。
这是在线参数放宽，训练集和检查点契约没有修改；记录在session和policy manifest中。
需要恢复旧限制可追加`--rgb-max-age-ms 250`。较旧图像可能造成滞后判断，这不修复相机延迟本身。

- RB（311）按住：人工优先，即使摇杆居中也不执行模型。RB+X（现场键码307）仍可调用已有返回功能。
- RB松开：丢弃接管期间的旧候选，只接收松开后的新模型候选。
- 手柄断开或没有待执行候选：仲裁输出零增量；输入无效时模型停止产生新候选。
- 按用户要求，新wrench脚本默认 `--candidate-expiry off`：模型发布前、仲裁接收和选取时均不再按100ms年龄拒绝候选。
  这不是关闭仲裁器；RB优先、切换屏障、未来时间戳拒绝、重复候选拒绝和每条只执行一次仍保留。
  延迟到达的旧候选可能执行一次，已在途/已缓存候选不会因传感器随后失效而自动撤回；不会持续重放旧动作。
  传感器头时间/接收时效、完整历史、有限值、动作限速和接收端自身断流保护不变。
  追加 `--candidate-expiry on` 可恢复原100ms拒绝。旧通用入口仍默认on。
  session/manifest记录开关，动作日志新增`selected_policy_age_ms`；启动时明确打印关闭警告。
- 模型缺少传感器时不阻塞独立手柄进程；模型进程发生致命错误则整套启动器停止，需要另开手柄才能继续。
- 按用户要求默认 `--policy-scale 1.0`，模型动作不做额外缩小；该参数不影响手柄。
- 默认 `--speed-mm-s 5 --rotation-deg-s 5` 同时定义手柄速度与模型候选的范数上限，10Hz时为0.5mm/0.5°每步。
  模型先逐分量乘训练动作尺度 `[0.0005m]*3 + [0.5°转rad]*3`，再乘policy-scale，最后分别限制平移/旋转范数。
- 若以后需要减小模型动作，可显式追加如 `--policy-scale 0.2`；默认保留模型原始物理动作。
- `--eef-reference raw` 与训练一致，不接受旧模型的 `bag-baseline-v1` 补偿。
- 手柄和模型在仲裁之后统一、仅一次转换到SDK毫米/ABC度：`sdk-x-forward-z-left`。

## 5. wrench输入门槛不是峰值触觉保护

每侧按 `Fx,Fy,Fz,Tx,Ty,Tz` 接收，取当前和之前9个100ms槽的最近历史消息，绝不取未来样本。
每槽最大接收年龄250ms，双侧20槽全部有效才允许推理；最新非法消息不能回退为旧的有效值。
在线另外检查 `frame_id=tactile_a/tactile_b` 和消息头年龄，错误、非有限值、过期均停发模型候选。
RGB/EEF/触觉网格保留原strict校验。时钟倒退清空历史，重新等待。

这些是**输入有效性门槛**，不是力峰值保护。接收端的 `tactile_guard_enabled` 仍默认false；
需要峰值保护须在接收端显式开启并设置阈值。手柄通道仍不受该模型触觉保护影响。
wrench仍是未标定SDK值，消息头和接收时效也不能证明设备内部数据一定更新。

## 验证记录

新增入口及原仲裁相关回归90项通过、1项跳过，覆盖缺失/过期/非法wrench、时钟重置、动作尺度、RB优先与旧候选丢弃。
第一包146条样本经新实时观测重建，与训练集逐字段完全一致。
隔离domain 118完成3秒无输入预览：30次门控均拒绝、候选发布0、无最终机器人发布者，手柄缺失保持暂停。
实际第200步检查点已在CUDA加载，并在四包各一条真实样本上确认新实时推理输出与训练推理完全一致。
首次GPU推理约468ms（仅在candidate-expiry=on时因100ms期限拒绝；off时完整有效历史的慢候选可发布），随后抽测约5–6.4ms；不是完整系统延迟保证。
开发期间未发布真机动作。仍需现场预览和小范围运动验收。
