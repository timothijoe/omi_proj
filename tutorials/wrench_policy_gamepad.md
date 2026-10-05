# 带六维力/力矩的 BC 模型：预览与真机手柄接管

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
与之前直接手柄测试不同，本入口固定使用：

| 来源 | 接收端参数 | 话题 |
| --- | --- | --- |
| 模型 | `delta_topic` | `/omi/action/decision` |
| RB手柄、RB+X | `manual_delta_topic` | `/omi/action/manual_decision` |

原来 `manual_delta_topic:=/omi/controller_test/decision` 不能直接沿用，否则接收不到本入口的手柄动作。
停止旧直控/策略发布进程，不允许多个控制器竞争。按现场流程停止并重启接收端，保留已确认的
机器人IP、A臂、base坐标系、TCP和控制参数，只将两个话题明确设置为：

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
