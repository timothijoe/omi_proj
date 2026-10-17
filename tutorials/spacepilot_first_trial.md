# SpacePilot 初版按键与单回合采集测试

记录日期：2026-10-17。本文记录本轮确认的按键方案和下一步测试指令；完整输入机制与其他入口见 [SpacePilot HIL 教程](spacepilot_hil.md)。

## 当前方案

3D 鼠标作为现有采集／RL Actor 的人工输入，不额外启动动作发布节点。默认输入仍是原手柄，旧命令无需修改；显式指定 `--input-device spacepilot` 才切换。

当前使用的配置为 `local/spacepilot/hil_buttons.json`，版本化副本为 [spacepilot_hil_oct17.json](../configs/spacepilot_hil_oct17.json)。

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
- 倍率相对于当前会话的基础速度，且受既有动作范围限制；不会放大策略输出或修改检查点／回放契约。
- ID26、27、28 虽然印有运动模式图标，本机驱动没有为其配置特殊动作，HIL 输入代码也不通过它们切换模式。

本预设要求 `review=auto`，不启用人工审阅。304／305 用于夹爪控制，不触发保留／丢弃；有效数据按现有流程自动保存，异常或无效数据仍受原有效性检查约束。

在线 RL 中松开 Menu 表示交还策略，不是结束回合。下面的人工采集入口没有策略接替；松开 Menu 后人工动作归零。

## 第一步：只读检查

先退出其他手柄、3D 鼠标或策略动作发送程序，避免它们同时响应按键。以下工具不连接 ROS 控制、不移动机械臂、不操作夹爪，也不会保存或执行标签跟随目标。

```bash
cd /home/zhoutong/omi_folder/omi_proj

.venv/bin/python scripts/configure_spacepilot_hil.py --show

.venv/bin/python scripts/configure_spacepilot_hil.py --preview \
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

沿用当前已验证的机器人接收端和传感器启动方式，并保持它们运行。接收端与采集进程需使用一致的 ROS domain/discovery 配置；Shell 入口默认使用 domain13、SUBNET。启动方式参见 [常用现场指令](common_live_commands.md)和[回合采集教程](rl_episode_collection.md)。

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
  --translation-scale 1.5 \
  --rotation-scale 0.3 \
  --spacepilot-mode all
```

看到等待开始提示后，按数字 1 开始；按住 Menu 操作旋钮，按 ALT 成功结束或 Ctrl 普通结束，也可等到回合超时。夹爪键按上表操作。回 home 只在回合外生效。

**本条人工采集入口不启用标签跟随，ID8／ID2 的实际功能留到在线 RL 入口测试。** 不能通过同时启动独立 `spacepilot_test.py --execute` 来补充这些功能；集成 Actor 已负责动作发布。

完成后检查终端回合结果和输出目录中的保存结果。成功标记与数据是否有效是两个不同判断，普通结束不等于丢弃数据。

## 验证状态与待测项

软件相关回归：319 项通过，2 项因当前解释器 CUDA 不可用而跳过。覆盖原手柄兼容、独立标签键不串入夹爪／回合事件、回位与跟随仲裁、倍率限幅，以及模式图标键不改变六轴映射。新预设的真实驱动只读连接已通过。

尚未完成本预设下的完整真机采集或在线 RL 验收。下一步记录 Menu 单独确认结果、实际运动与夹爪行为、回合结束及数据保存结果；随后再验证在线 RL 的人工接管／还权和两个标签键。共用接收端的物理停止拖尾不属于本轮按键修改范围。
