# 独立手柄录包、数据检查与逐帧可视化

2026-10-09 存储更新：既有 `local/bags` 和 `local/four-demo-audit-20261005` 已外置，
原路径软链接兼容，旧包查看需挂载移动盘。后续录制若需保留本机，应选择新的本机输出目录，
见[存储教程](local_data_storage.md)。

2026-10-05采集更新：白名单新增腕部可靠录制topic与各传感器元数据，转换时保留独立字段时间，查看器新增时间审计面板。见[独立采集教程](sensor_decoupling.md)。旧包无需修改。

当前使用两个独立进程：`gamepad_test.py` 遥操作，`record_demo_bag.sh` 只录包。
训练更新：四个日期bag已通过新的[含wrench的BC转换与训练入口](passive_bag_bc_wrench.md)
生成1005条样本并启动CUDA训练。下述`passive_preview`仍是独立审阅格式，不直接作为训练数据。
已完成四个真实bag的检查及第三包335条观测—实际指令配对预览；[检查记录](../docs/agent/training/chronicles/2026-10-05-passive-demo-audit.md)和[数据契约](../docs/agent/training/evolution/demo-collection-bc.md)说明适用范围。

## 1. 启动手柄

先按[机器人接收端与手柄启动步骤](robot_gamepad_startup.md)启动传感器和接收端。
以下是用户确认的现场手柄命令；已有手柄进程运行时不要重复启动：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=1
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

.venv/bin/python scripts/gamepad_test.py \
  --execute --device /dev/input/js0 \
  --topic /omi/controller_test/decision --rate 10 \
  --home-button-code 307 --scale 0.5 \
  --output-convention sdk-x-forward-z-left
```

按回车开始发布，按住RB操作摇杆。普通遥操作速度上限为5mm/s、5°/s；10Hz下增量上限对应0.5mm、0.5°。
输出是SDK坐标系XYZ毫米和ABC角度，不是策略坐标系的m/rad旋转向量。
RB+X会进入自动返回，不能自动算作人工示范；按钮映射、夹爪及返回行为以手柄教程为准。

## 2. 另开终端，只录包

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13
scripts/record_demo_bag.sh \
  --directory "local/bags/demo_$(date +%Y%m%d_%H%M%S)" \
  --command-topic /omi/controller_test/decision
```

Ctrl+C停止；加 `--duration 15` 可在录制器准备好后15秒自动停止。
不需要 `--execute` 或 `--episodes`，脚本也不接受这两个参数。
它不读取手柄、不发布机器人指令、不实现Menu开始/Y成功/A保留/B丢弃。
各按钮仍归独立手柄程序管理。建议一次尝试单独录一个bag，并另外记下成功时刻、失败或返回段。

默认使用明确topic列表，不加 `--all-topics`。上次10秒全topic测试包约860MiB，包含额外深度图、压缩图和看板消息。
需要额外传感器可重复添加 `--raw-topic /your/topic`。`--command-topic` 必须与手柄实际的 `--topic` 一致。

| 内容 | 默认录制topic |
|---|---|
| 外部RGB | `/camera/camera/color/image_raw` |
| 腕部原图、ROI | `/omi/wrist/color/image_raw`、`/omi/wrist/color/image_roi` |
| EEF、关节反馈 | `/tj/info/eef_left`、`/tj/info/joint_feedback` |
| 双指三场和六维力/力矩 | `/omi/tactile_grid24x16/{a,b}/{deformation,shear,depth,wrench}`，展开为8个topic |
| 当前手柄输出 | `/omi/controller_test/decision`，可通过参数修改 |
| 标准控制输出 | `/omi/action/decision`、`/omi/action/manual_decision` |
| 可用时录制的审计信息 | `/omi/action/command_trace`、`/omi/action/receipt`、`/omi/demo/event`、`/omi/demo/sample` |

列表只表示订阅意图；无发布者时不会产生消息。
当前独立 `gamepad_test.py` 不生成精确样本快照、command ID、逐指令SI trace或回合审核事件。
本次四包没有receipt消息；这不等于没有机器人动作，也不能反过来证明每条指令已执行。

输出目录：

```text
local/bags/demo_时间戳/
  raw/metadata.yaml
  raw/raw_0.db3
  session.json          # 录制模式、domain、topic；不等于手柄参数快照
  raw_recording.json    # 实际消息数、请求但无消息的topic
  rosbag.log
```

原始bag按各topic实际频率保存，不统一抽成10Hz。它不会因为模型header检查不通过就拒绝记录。
所有输出使用新目录，避免覆盖原始采集。

## 3. 检查真实bag

```bash
source scripts/env_ros.sh
source local/ros2/robot_controller_ws/install/local_setup.bash
python -m omi_hil_rl.training.passive_audit \
  --sessions local/bags/demo_20261005_204815 local/bags/demo_20261005_204853 \
             local/bags/demo_20261005_204949 local/bags/demo_20261005_205111 \
  --output local/four-demo-audit-new
```

加载控制端的local_setup是为了使用现场实际的消息定义。
本机另有同名 `marvin_msgs/Jointfeedback` 的不兼容定义；错用它会导致反序列化失败，并不说明bag损坏。

检查包括SQLite完整性、metadata计数、topic覆盖、消息解码、形状、有限值、频率/间隔、header年龄、非零指令数及严格十帧窗口数量。
结果写入各包的 `audit.json`、`commands.jsonl` 和总 `summary.json`。
header age包含时钟差、传输和处理时间，不能直接当成传感器自身延迟。

## 4. 导出真实指令预览

```bash
source scripts/env_ros.sh
source local/ros2/robot_controller_ws/install/local_setup.bash
python -m omi_hil_rl.training.passive_preview \
  --session local/bags/demo_20261005_204949 \
  --output local/passive-preview-new
```

此入口直接读取原始观测和控制topic，不依赖 `/omi/demo/sample`，也不执行 `ros2 bag play`。
每条保留的预览样本要求：

1. 当前/下一观测均有完整十帧历史，双相机和触觉/EEF通过现有strict header规则。
2. 两个参考时刻相隔100ms，其间恰好录到一条六维指令。
3. 下一窗口的EEF消息接收时间晚于指令接收时间。
4. 双指wrench按各历史槽之前最近的接收消息对齐，最大年龄250ms，缺失/无效标mask。

原始指令以 `recorded_wire_action` 保存，不归一化、不逆算坐标、不以未来EEF差分替代。
这是bag接收时钟下的保守配对，不证明发送端精确输入或物理执行。过滤可能造成样本间跳跃，播放间隔不是原始时间轴。
输出独立 `omi-passive-wire-preview-v1` 格式，现有BC入口会拒绝误当accepted-command训练示范。
正常人工BC与RL导入仍需完成动作语义、成功/失败和返回段审核。

新的导出默认显示generic wire分量，不猜单位。本次第三包已经依据用户确认命令在manifest加入 `wire_units=mm,SDK_ABC_degrees` 与 `publisher_provenance`，显示XYZ(mm)/ABC(°)。
其证据保存在 `local/four-demo-audit-20261005/publisher_provenance.json`；`--scale`、转换约定等不能从录制器配置倒推。

## 5. 打开可视化与键盘操作

现有第三包335条真实指令预览：

```bash
scripts/view_demo_dataset.sh \
  --dataset local/four-demo-audit-20261005/preview-204949 --port 8767
```

打开 `http://127.0.0.1:8767`；直接定位示例为 `http://127.0.0.1:8767/?step=242`。
若该端口已有查看器在运行，直接打开；新开实例可用另一个 `--port`。
一般入口默认端口8766，Ctrl+C停止查看器。

| 操作 | 效果 |
|---|---|
| 键盘 ← / → | 上一帧 / 下一帧，并暂停播放；首尾不越界 |
| 上一帧 / 下一帧按钮 | 与键盘同样行为 |
| 进度条、episode选择 | 切换样本或回合 |
| 播放 / 暂停 | 按浏览间隔播放，受渲染耗时影响 |
| 历史帧0～9 | 0为900ms前，9为当前；不重新配对动作 |
| next observation | 查看同一动作配对的下一观测 |

下拉框、文本输入获得焦点时保留原生键盘操作；如左右键正在调整下拉项，点击图像或页面空白后再按。
带Ctrl/Alt/Meta/Shift的方向键不拦截。页面源码更新后刷新浏览器生效。

当前布局为两列，浮点读数保留四位小数：

- 左列：双相机实际128×128输入、动作数值/条形图、EEF和时间信息。
- 右列最上方：A/B各指Fx/Fy/Fz、Tx/Ty/Tz、frame/header、有效状态及一秒历史曲线；下方为deformation、shear、depth。

wrench单位仍是未确认N/Nm的SDK原值；mask=0显示缺失，存储占位0不代表真实零力。
原始纳秒时间戳保留整数，显示取舍不改变磁盘数组精度。
真实wire预览的条形图相对该包各分量最大值缩放，**不是policy的[-1,1]动作标签**。
因此最右端不是统一的0.5或1，而是该包对应分量的正向显示上限；例如该分量最大绝对值为0.5°时，右端对应+0.5°。条长缩放和四位小数仅影响显示，不修改原始bag或数据集动作值。
集成collector的accepted-command数据则显示自身归一化动作，两种含义不能混用。
查看器没有3D机器人模型，不发布机器人指令；按需读取样本，不把全部图像加载进内存。

单帧PNG导出：

```bash
scripts/view_demo_dataset.sh \
  --dataset local/four-demo-audit-20261005/preview-204949 \
  --episode 0 --step 242 --slot 9 --export-frame local/demo-frame-242-new.png
```

## 6. 现有四包与时间信息

| 包 | 时长(s) | 指令数 | 非零指令 |
|---|---:|---:|---:|
| 204815 | 17.4212 | 166 | 128 |
| 204853 | 22.7826 | 211 | 136 |
| 204949 | 52.4814 | 503 | 319 |
| 205111 | 22.3221 | 206 | 140 |

第三包导出335条，其中240条动作非零，双指各3350个历史槽有效。
各样本对间隔100ms，但样本之间有一次16.9秒跳跃，主要来自指令临近网格末端时尚未收到后继EEF的保守筛选；不等于该段原始数据全部错误。
这里“缺后继EEF”指指令到达后、下一参考时刻之前没有收到符合要求的新EEF，并不表示该时段完全没有EEF反馈，也不能单凭这项筛选推断EEF频率低。例如下一参考时刻为100ms、指令在99ms到达，最近EEF在98ms、下一条在118ms，则此候选仍被排除。此例仅解释配对规则，不是实测时间。正式passive BC不要求后继EEF；167条被排除的数字仅来自第三包预览，不推广到其他包。
少数观测过旧或有约0.3～0.4秒接收间断，需要按用途清洗。
原始四包没有成功标记，也尚未确认是否使用自动返回，因此不能自动认定整包都是成功人工示范。
详情见[四包检查编年](../docs/agent/training/chronicles/2026-10-05-passive-demo-audit.md)。

## 7. 其它两种数据入口

| 模式 | 用途 | 转换入口 |
|---|---|---|
| 当前独立gamepad录包 | 真实传感器＋实际wire指令的人工检查 | `training.passive_preview`；review-only |
| 集成collector | 自己读手柄，保存精确窗口、ID/回执、审核事件 | `scripts/bag_to_demo_dataset.sh`；见[集成采集与BC教程](demo_collection_bc.md) |
| 零动作诊断 | 真实传感器＋未发送的全零占位动作 | `training.zero_preview`；不能代替真实手柄标签 |

**不能把当前独立gamepad包直接交给快照转换器**：它要求 `/omi/demo/sample` 和episode事件。
`hil.demo collect` 集成模式仍保留，但不与独立手柄程序同时运行。

此前10秒零动作实验位于 `local/zero-action-live-20261005/`：70条预览，外部RGB header age中位约490ms，strict完整窗口为0，只能用receive-only-diagnostic查看。
补齐wrench版本是 `dataset-wrench/`，与当前真实指令335条预览区分。

需要复现该诊断处理时：

```bash
source scripts/env_ros.sh
python -m omi_hil_rl.training.zero_preview \
  --bag local/zero-action-live-20261005/raw --output local/zero-preview-new
python -m omi_hil_rl.training.demo_wrench \
  --dataset local/zero-preview-new --bag local/zero-action-live-20261005/raw \
  --output local/zero-preview-wrench-new
```

wrench辅助字段为 `[10,2,6]`，mask、接收时间、header为 `[10,2]`，各槽frame_id在元数据中。
三场触觉使用当前＋过去9帧、10Hz历史，每帧CNN提取96维后按时间拼接。
预览中的wrench仍为辅助字段；新BC recipe已通过独立MLP分支使用同样的双指十帧wrench，
见[训练教程](passive_bag_bc_wrench.md)，不要据此把旧checkpoint视为已支持新输入。
