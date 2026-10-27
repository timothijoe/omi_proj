> 历史资料：原路径 `tutorials/spacepilot_first_trial.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../modules/teleoperation.md)；本页保留原过程与证据。

# SpacePilot 初版按键与单回合采集测试

记录日期：2026-10-17。本文记录本轮确认的按键方案和下一步测试指令；完整输入机制与其他入口见 [SpacePilot HIL 教程](../../../../tutorials/spacepilot_hil.md)。

调整前备份提交：`7c2d2c5`。本文命令已更新为参考 `spacepilot_test.py` 的响应版本：新建人工采集使用相同速度基准，首次有效动作与回中立即发送，持续运动10Hz。

## 当前方案

3D 鼠标作为现有采集／RL Actor 的人工输入，不额外启动动作发布节点。默认输入仍是原手柄，旧命令无需修改；显式指定 `--input-device spacepilot` 才切换。

当前使用的配置为 `local/spacepilot/hil_buttons.json`，版本化副本为 [spacepilot_hil_oct17.json](../../../../configs/spacepilot_hil_oct17.json)。

| 3D 鼠标实体键 | 设备 ID | 原手柄功能 | 当前操作 |
| --- | ---: | --- | --- |
| Menu | 0 | RB / 311 | 按住人工接管；回合外手动移动 |
| 数字 1 | 12 | Start / 315 | 开始回合 |
| ALT | 23 | 成功键 / 308 | 标记成功并结束回合 |
| Ctrl | 25 | 普通结束键 / 307 | 提前结束，不标成功 |
| ALT 左右对称键 | 26 | Back / 314 | 回合外返回 home |
| Esc 左右对称键 | 28 | A / 304 | 夹爪闭合 |
| Ctrl 左右对称键 | 27 | B / 305 | 夹爪张开 |
| 本轮选定的第一个标签键 | 8 | LB+A | 单键开启／停止标签跟随 |
| 本轮选定的第二个标签键 | 2 | LB+B | 单键保存当前标签与末端的关系 |

数字 1、ALT、Ctrl、三个对称键和两个标签键均已单独监听确认。Menu 的 ID0 根据前两轮按动顺序对应，首次预览时再单独核对。两个标签键的实体图标名称尚未补录。

数字 3（原接管键 ID19）在本预设中空置。Esc 和用户描述的 `←` 未从当前 3Dmouse USB 按键接口捕获到，暂不绑定；设备另有屏幕控制接口，因此不能仅凭这次监听断定硬件损坏。

## 速度、模式与数据保留

- 人工平移倍率：`--translation-scale 1.5`。
- 人工旋转倍率：`--rotation-scale 0.3`。
- 本次采用 `--spacepilot-mode all`，允许六轴运动，不开启单轴优先。
- 本文新建采集显式使用 `--spacepilot-speed-profile standalone`，基准为10 mm/s及10°/s；1.5／0.3对应平移合速度上限15 mm/s、旋转角速度上限3°/s，与独立工具一致。
- 新数据集在创建时记录足够的动作范围。它与旧5.77 mm/s单轴范围的数据／模型不是同一归一化契约，不能直接混池或冒充旧checkpoint的数据。需要沿用旧范围时改用 `--spacepilot-speed-profile session`。
- 已有模型／会话默认保留其原动作范围；不会静默扩大旧模型输出。显式请求standalone而范围不足时会在连接设备前拒绝。
- ID26、27、28 虽然印有运动模式图标，本机驱动没有为其配置特殊动作，HIL 输入代码也不通过它们切换模式。

本预设要求 `review=auto`，不启用人工审阅。304／305 用于夹爪控制，不触发保留／丢弃；有效数据按现有流程自动保存，异常或无效数据仍受原有效性检查约束。

在线 RL 中松开 Menu 表示交还策略，不是结束回合。下面的人工采集入口没有策略接替；松开 Menu 后人工动作归零。

## 第一步：只读检查

先退出其他手柄、3D 鼠标或策略动作发送程序，避免它们同时响应按键。以下工具不连接 ROS 控制、不移动机械臂、不操作夹爪，也不会保存或执行标签跟随目标。

```bash
cd /home/zhoutong/omi_folder/omi_proj

.venv/bin/python scripts/configure_spacepilot_hil.py --show

.venv/bin/python scripts/configure_spacepilot_hil.py --preview \
  --spacepilot-speed-profile standalone \
  --translation-scale 1.5 \
  --rotation-scale 0.3
```

依次检查：

1. Menu 按下时出现逻辑按钮 311，松开后消失。
2. 数字 1 显示逻辑 315；ALT 显示 308；Ctrl 显示 307。
3. 三个对称键分别显示 314、304、305。
4. 第一个标签键打印“开启/停止跟随”预览；第二个打印“保存关系”预览。
5. 按住 Menu 后推动／倾转旋钮，六轴人工动作有变化；松开 Menu 后预览动作归零。

按 Ctrl+C 退出预览，再开始实际采集。

## 第二步：完整单回合采集指令

沿用当前已验证的机器人接收端和传感器启动方式，并保持它们运行。接收端与采集进程需使用一致的 ROS domain/discovery 配置；Shell 入口默认使用 domain13、SUBNET。启动方式参见 [常用现场指令](../../../../tutorials/common_live_commands.md)和[回合采集教程](../../../../tutorials/rl_episode_collection.md)。

下面命令创建一个带时间戳的新目录，执行一个最长 20 秒的人工采集回合，默认启用原采集入口的夹爪控制：

```bash
cd /home/zhoutong/omi_folder/omi_proj

bash scripts/collect_rl_episodes.sh \
  --output "local/rl_episodes/spacepilot_test_$(date +%Y%m%d_%H%M%S)" \
  --episodes 1 \
  --episode-seconds 20 \
  --execute \
  --input-device spacepilot \
  --spacepilot-map local/spacepilot/hil_buttons.json \
  --spacepilot-speed-profile standalone \
  --translation-scale 1.5 \
  --rotation-scale 0.3 \
  --spacepilot-mode all
```

看到等待开始提示后，按数字 1 开始；按住 Menu 操作旋钮，按 ALT 成功结束或 Ctrl 普通结束，也可等到回合超时。夹爪键按上表操作。回 home 只在回合外生效。

`--episode-seconds 20`表示每回合最长20秒，**不是满20秒就判成功**。开始键触发回合计时；ALT在期限内标记成功并结束，Ctrl提前普通结束，期限到达仍未标成功则超时结束。有效的非成功回合也可自动保存，供后续RL学习。

**本条人工采集入口不启用标签跟随，ID8／ID2 的实际功能留到在线 RL 入口测试。** 不能通过同时启动独立 `spacepilot_test.py --execute` 来补充这些功能；集成 Actor 已负责动作发布。

完成后检查终端回合结果和输出目录中的保存结果。成功标记与数据是否有效是两个不同判断，普通结束不等于丢弃数据。

## 验证状态与待测项

软件相关回归：319 项通过，2 项因当前解释器 CUDA 不可用而跳过。覆盖原手柄兼容、独立标签键不串入夹爪／回合事件、回位与跟随仲裁、倍率限幅，以及模式图标键不改变六轴映射。新预设的真实驱动只读连接已通过。

上述319项是备份前版本。响应调整后的相关回归341项通过、2项CUDA测试跳过，另覆盖与独立工具六轴数值一致、启停时间、旧契约不变和训练导出。新调度逐条记录指令；重复使用同一观测、持续不足80ms或超过150ms、被中途外部停止的相关片段只保留审计，不生成虚假的100ms训练步。有效片段记录实际指令间隔。

用户先在初版下试采两段反馈手感差异，响应调整后又完成10回合新采集，9个正常回合用于BC6148训练，并已启动在线RL；见[当天编年](../../online-rl/records/training/chronicles/2026-10-17-spacepilot-bc-online-rl.md)。本页的单回合流程仍可用于复查，但不代表独立闭环精度或停止性能验收。两个标签键在当前主RL setting中暂时禁用，未来隔离后再测。共用接收端的物理停止拖尾不属于本轮按键修改范围。
