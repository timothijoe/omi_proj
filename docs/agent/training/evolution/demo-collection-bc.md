# 手柄示范录包、动作语义与 BC 数据入口

最新进展：[四个真实日期包已转换并完成首轮含wrench的BC训练](../../../../tutorials/passive_bag_bc_wrench.md)。后续其他agent的重训与现场诊断见[最新编年](../chronicles/2026-10-05-policy-input-audit-no-wrench.md)，不将这些工作归于本窗口。
新schema明确采用recorded-command监督，1005条样本按完整bag划分844/161；
不复用review-only预览的schema，也不提升为accepted-command RL经验。
`hil.networks.Encoder`新增可选双指六维wrench十帧分支，旧recipe仍不含该分支。
以下“尚未接入/待训练”描述保留为此次开发前的阶段背景；当前结果以上述教程及编年为准。

当前现场选择独立 `gamepad_test.py` 遥操作，`record_demo_bag.sh` 只订阅录包。
四个真实包已检查，第三包335条观测—实际wire指令已可视化。操作见[录制与查看教程](../../../../tutorials/demo_bag_dataset.md)，结果见[四包编年](../chronicles/2026-10-05-passive-demo-audit.md)。

## 三种入口及各自的证据

| 入口 | 动作来源和证据 | 当前用途 |
|---|---|---|
| 独立gamepad＋`hil.record_bag` | 实际Float64MultiArray输出；本次无逐指令ID、receipt和操作者模式 | 原始采集；`passive_preview`生成review-only数据 |
| 集成 `hil.demo collect` | 采用的SI动作、SDK wire、ID/回执、精确观测快照、回合审核 | 对应自己的demo schema，可做BC；并非当前现场默认 |
| `training.zero_preview` | 人工指定的全零占位，未下发机器人 | 传感器诊断，不作人工动作标签 |

纯录包模式没有Menu开始/Y成功/A保留/B丢弃逻辑，不读取手柄、不发送控制，不要求先通过模型header检查。
默认记录明确topic列表，包含现场 `/omi/controller_test/decision` 和双指wrench；不默认all-topics。
`/omi/demo/sample` 等审计topic仅在有发布者时有消息，不能因列入订阅列表就认为已经具备精确样本快照。

## 当前动作与时间语义

用户确认手柄10Hz、scale=0.5、`sdk-x-forward-z-left`，普通遥操作指令速度上限为5mm/s和5°/s。
wire顺序XYZ/ABC，单位mm/度；不是policy坐标系的m/rad旋转向量。自动返回模式及成功时刻没有写入当前bag，仍需人工审核。
“收到控制topic”“SDK采纳指令”“机器人完成物理运动”是三个不同证据层级，本次四包只具备第一个。

原始bag按各源实际频率录制。正式网络历史为10Hz十槽，即t−0.9s到t；每个槽取符合规则的因果观测，不声称所有设备在同一时刻采样。
`passive_preview`检查严格header和完整历史，要求两参考时刻相隔100ms、其间恰好一条指令，并有接收时间晚于该指令的下一EEF。
匹配基于recorder时钟，不等于发送端窗口。无效/缺失窗口不补造；相邻保留样本可能跳跃。
第三包335条中出现一次16.9秒跳跃，主要受指令到达相位与后继EEF条件影响，不能据此把全部被排除原始数据判错。

strict规则目前拒绝EEF header年龄超过50ms、其它所用传感器超过250ms、header领先接收时刻超过100ms。
通过这些规则不等于硬件同步或时钟标定完成。新四包RGB中位约70～84ms；先前零动作测试包约490ms，是不同实验。

## 触觉历史、wrench和查看器

网络的三场触觉输入为 `[B,10,10,16,24]`：10时间槽、每槽双指合计10通道。
每帧共享触觉CNN提取96维，十帧按时间顺序拼接，再与视觉、EEF、mask融合；不是只用当前帧，也不是该分支的GRU。

本窗口最初为查看器添加的六维wrench是辅助观测：`wrench[10,2,6]`、`wrench_mask[10,2]`、原始header/接收时间和frame_id。后续正式passive BC已新增可选wrench网络分支，不能再把“尚未进入网络”当作整个项目当前状态。
各槽采用不晚于该槽时刻的最近消息，接收年龄上限250ms；mask=0不表示真实零力。保留SDK原单位，不声称已校准N/Nm，不擅自换坐标。

查看器左列为双相机、动作和时间；右列最上方为六维力/力矩及曲线，下方为deformation/shear/depth。
浮点读数四位小数；历史槽和next observation同步更新；原始精度不变。
键盘←/→与上一帧/下一帧按钮等效并暂停播放，首尾不越界；输入框/下拉框编辑及组合键保留浏览器原生行为。
真实wire条形图按该包每分量最大值显示，不能当作policy归一化标签。支持 `?step=242` 定位及PNG导出。

## 集成collector与BC（另一路径）

[集成教程](../../../../tutorials/demo_collection_bc.md)使用 `hil.demo collect`，不依赖learner或初始策略。
它自己读取手柄，保存当前/下一窗口、SI动作、SDK动作、command trace/receipt和 `/omi/demo/sample` 精确快照。
开始后默认15秒，包括历史预热；纯人工阶段需RB，成功/超时后人工审核。停止/复位仅录原始消息，不作训练标签。
`bag_to_demo_dataset.sh`仅读取这类包含sample/event的bag；不是独立gamepad包的通用转换器。

采集文件的reward可用独立版本sidecar后补，BC不使用reward；没有RL的ready.json就不会自动流入learner。
BC按完整episode划分，训练集统计独立计算，磁盘按需读取；复用current9stack六维Actor，冻结官方ResNet-10。
软件合成闭环、真实多模态CPU/CUDA梯度与隔离ROS录包验证通过。当时四包尚未训练；随后正式passive BC已完成训练，仍无插入成功率验收结论。
集成demo、零动作诊断和未验证wire预览使用不同schema，避免误混标签；BC到SAC的自动权重初始化仍未实现。

## 待完成的实际训练准备

补充各包成功/失败时刻，辨别普通示范、静止和自动返回段。正式passive BC的动作转换、因果对齐和整包训练/验证划分已另行实现，细节以上方教程为准。
如需RL accepted-command数据，还需逐指令证据和完整reward/终止语义。
是否使用wrench取决于具体模型recipe/checkpoint；查看器能显示wrench本身不能证明所加载模型使用了它。

采集端后续解耦、record优先与逐槽时间审计见[实现纪传体](../../hardware/evolution/sensor-decoupling.md)；外部RGB时钟与接收年龄见[时间基准专题](../../hardware/evolution/sensor-time-alignment.md)。
