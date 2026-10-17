# SpacePilot 用于 BC/RL 采集与在线交互

首次测试可直接使用[初版键位与单回合采集指令](spacepilot_first_trial.md)。

手柄仍为默认输入，原命令无需修改；只有显式传 `--input-device spacepilot` 才切换。SpacePilot在原Actor内部提供人工输入，不另开动作发送节点，沿用现有回合、模型仲裁、回执和训练数据链。

## 1. 2026-10-17 确认的初版键位

当前配置已保存到 `local/spacepilot/hil_buttons.json`，可追踪副本为
[`configs/spacepilot_hil_oct17.json`](../configs/spacepilot_hil_oct17.json)。本机数字1实测ID12；Menu的ID0来自两轮按动顺序，首次预览时再核对一次。

| SpacePilot实体键 | 设备ID | 功能 / 原手柄逻辑码 |
| --- | --- | --- |
| Menu | 0 | 按住人工接管、回合外手动移动 / RB 311 |
| 数字1 | 12 | 开始回合 / Start 315 |
| ALT | 23 | 成功并结束 / 308 |
| Ctrl | 25 | 普通结束，不标成功 / 307 |
| ALT左右对称键 | 26 | 回合外返回home / Back 314 |
| Esc左右对称键 | 28 | 夹爪闭合 / A 304 |
| Ctrl左右对称键 | 27 | 夹爪张开 / B 305 |
| 用户选的第一个标签键 | 8 | 单键开启/停止标签跟随 / 原LB+A |
| 用户选的第二个标签键 | 2 | 单键保存当前标签关系 / 原LB+B |

数字3（ID19）在本预设中不再接管。Esc及用户描述的`←`键未从当前USB按键接口捕获到，暂不分配。标签键实体图标待补，ID8/2已逐次确认。

本机驱动26/27/28没有特殊动作绑定。HIL入口不会因为这些键的模式图标而切换平移、旋转或单轴模式；相关模式由CLI参数决定。软件回归覆盖按这些键前后六轴映射不变。

**本预设只允许 `review=auto`，不启用人工审阅。** 304/305不会触发保留/丢弃。旧人工审阅模式可能在回合内将305视为中止，夹爪也没有自动按审阅阶段隔离，因此不要把本预设用于手动审阅配置。成功/普通结束与数据有效性保留规则仍沿用原入口。

标签功能只在原入口已启用时生效；固定BC入口原本没有夹爪控制，选择本预设也不会额外启用。独立标签键只进入标签仲裁，不向夹爪或回合事件伪造A/B。原手柄仍用LB+A/B，旧SpacePilot组合键profile也仍可使用。

**在线RL松开Menu会交还策略，不等于结束回合或物理急停。** 普通结束用Ctrl，成功结束用ALT；回合外松开Menu沿用归零行为。

## 2. 先只读预览

先退出其他手柄、SpacePilot、策略动作发送程序。工具本身不发布动作，但不能阻止其他程序响应同一设备。

```bash
cd /home/zhoutong/omi_folder/omi_proj
.venv/bin/python scripts/configure_spacepilot_hil.py --show
.venv/bin/python scripts/configure_spacepilot_hil.py --preview \
  --translation-scale 1.5 --rotation-scale 0.3
```

预览显示逻辑键和归一化人工动作；按ID8/2会明确打印标签操作预览，不实际保存或跟随。先确认Menu按住时出现逻辑311，数字1出现315，其他键对应上表，再按住Menu推拉、倾转旋钮。

更换设备或重建配置时，不要假定实体ID相同。以下命令保留已确认布局、只询问数字1的实际ID，旧文件不会覆盖：

```bash
.venv/bin/python scripts/configure_spacepilot_hil.py \
  --preset oct17 --output local/spacepilot/hil_buttons_new.json
```

已测得数字1的ID时可加 `--start-button-id 12` 离线生成。自定义布局可不传preset，使用逐键向导；加 `--direct-follow` 选择独立标签键，否则仍配置原LB组合键。已有会话自定义逻辑码时加 `--config 已有会话/config.json`，home逻辑码需匹配 `--home-button-code`。

## 3. 原命令加哪些参数

SpacePilot CLI倍率默认平移1.5、旋转0.3，也支持简写 `--translation-scale` / `--rotation-scale`。这些选项不改变手柄速度。以下入口均支持同一组输入参数：

| 入口 | 用途 |
| --- | --- |
| `bash scripts/collect_rl_episodes.sh` | 人工示范/BC来源数据、人工RL回合采集 |
| `bash scripts/run_bc_episodes.sh` | 固定BC策略交互及人工接管录制，无Learner |
| `bash scripts/run_async_rl.sh` | 异步在线RL与人工接管 |
| `bash scripts/run_alternating_rl.sh` | 交替采集/学习兼容入口 |
| `python -m omi_hil_rl.hil.demo collect` | 旧集成BC示范采集，ROS配置 |
| `python -m omi_hil_rl.hil.actor` | 旧同步Actor，ROS配置 |

保留原命令的run/output、模型、传感器、batch和回合参数，在末尾加：

```text
--input-device spacepilot
--spacepilot-map local/spacepilot/hil_buttons.json
--spacepilot-translation-scale 1.5
--spacepilot-rotation-scale 0.3
```

例如新建人工采集目录（先完成原有接收端/传感器准备）：

```bash
bash scripts/collect_rl_episodes.sh \
  --output local/rl_episodes/spacepilot_demo_trial_01 \
  --episode-seconds 20 --episodes 10 --execute \
  --input-device spacepilot \
  --spacepilot-map local/spacepilot/hil_buttons.json \
  --spacepilot-speed-profile standalone \
  --spacepilot-translation-scale 1.5 --spacepilot-rotation-scale 0.3
```

新目录必须未存在；续采仍按原入口规则使用 `--resume`。在线RL仍用原来的 `--run` 自动续跑，不重新prepare。不使用夹爪的原命令继续保留 `--no-gripper`。不传输入选项或显式 `--input-device gamepad` 就是原手柄流程，`--gamepad` 路径照常有效；选择SpacePilot时不要求 `/dev/input/js0` 存在。

这些参数用于上述直接入口；一键动作菜单保持原手柄流程。集成运行时**不要再启动 `spacepilot_test.py --execute`**，Actor已经独占动作话题。HIL入口也不使用独立工具的 `--enable-button`：接管键由profile中的逻辑311映射决定。

## 4. 六轴与速度契约

六轴全部保持连续量，Z/Rz不会被量化成十字键开关。前+X、左+Y、上+Z及roll方向沿用已验证输入映射，SDK换轴/ABC转换只在原发布出口执行一次。

可用 `--spacepilot-mode translation|rotation|all` 和 `--spacepilot-dominant-axis`，死区由 `--spacepilot-deadzone` 指定，默认18、量程参考350。

`--spacepilot-speed-profile`决定速度基准：

| 方案 | 速度及数据范围 |
| --- | --- |
| `auto`（默认） | 新建且未指定config的人工采集使用standalone；模型入口或显式旧config使用session；续采读取已保存方案 |
| `standalone` | 与spacepilot_test.py相同的10 mm/s、10°/s基准；倍率1.5/0.3输出15 mm/s、3°/s，新建人工采集同时建立足够的动作范围 |
| `session` | 保持原会话/模型的速度基准和动作边界，不修改数据或权重 |

standalone遇到范围不足的旧会话/模型会提前拒绝，不能通过静默限幅伪装成速度匹配。新采集扩大后的physical_action_scale须随数据使用，不能直接混入旧范围的模型或回放池。恢复备份前的速度方案可显式选择session。

session方案中，倍率1的单轴基础速度为：

- 平移：`config.translation_step_m × config.hz` m/s。
- 旋转：`config.rotation_step_rad × config.hz` rad/s。

独立倍率只影响人工输入，0禁用对应组；session方案缩放后如果超过会话逐轴动作上限，按组等比例压回界内。standalone则在启动前验证整个动作范围可容纳，不靠早饱和改变响应曲线。已存在的checkpoint/replay契约及策略输出不变。回home仍沿用原固定回位算法，不由旋钮倍率调速。

## 5. 仲裁、断连和数据

periodic人工采集和immediate仲裁下的SpacePilot人工控制使用与独立工具共用的MotionSchedule：首次非零/归零立即发送，连续运动按墙钟10Hz、方向变化等待下个周期、不补发积压指令。输入不再等待新观测才能发送，仍使用最新可用观测做审计。观测不可用时停止已有人工运动。回合外手动调整也采用相同节拍。

原手柄仍按原观测驱动节拍运行。在线RL显式选择after-inference时仍保留推理完成后仲裁，不能声称此模式下人工输入完全等同独立工具；要即时人工响应使用--arbitration-mode immediate。旧receipt采集入口仍保留原逐条配对机制。

每条额外启停指令记录manual_timing和真实发送时间。相关训练片段必须有递增观测、实际指令间隔80–150ms且没有中途外部停止；过短或重复观测片段仅保留审计并分段，避免伪造完整训练步。有效导出记录actual_command_interval_s。原手柄/旧数据未添加该调度标记，保持原录制规则。

输入超过150 ms未更新时人类候选为零；仍按住接管键时不会因此伪装成policy。设备断连/变更清空状态；轮询停顿超过250 ms丢弃连接中旧事件，并按断连处理。启动或重连时已经按住的键不自动触发，需要松开再按。

原动作来源仍为human/policy；人工动作trace增加 `operator_input`，含设备类型、profile哈希、倍率和动作上限。profile文件在预检后被改变会拒绝构造运行输入。回放契约和旧数据格式不变，回合外复位仍不入池，标签跟随的control_epoch隔离不变。

当前已写入本轮实测键位并完成真实驱动只读连接；尚未用新集成入口运行真机采集或训练。执行前先完成profile预览，再按原流程做一段人工回合检查。已有停止拖尾问题属于共用接收端，本轮没有更改其执行方式。
