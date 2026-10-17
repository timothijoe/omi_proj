# SpacePilot 人工采集、BC6148 与显式参数在线 RL

更新于2026-10-18。本页按功能记录当前实现；形成过程见[当天编年](../chronicles/2026-10-17-spacepilot-bc-online-rl.md)。实际命令以[在线操作教程](../../../../tutorials/spacepilot_bc6148_online_rl.md)和[主参数文件](../../../../configs/spacepilot_bc6148_online_rl.json)为准。

最新停止状态：10月17日23:42 Actor/Learner正常退出，最终两份checkpoint均4628，退出前操控使用4150；67个原始回合中66可训练，13360条均已登记，累计上限剩余233。10月18日只读检查保存状态与索引通过；[停止核验](../chronicles/2026-10-18-spacepilot-rl-stopped.md)记录完整口径及续跑边界。以下23:29数值保留为历史运行快照。

## 当前可用范围

SpacePilot已接入人工BC/RL采集、固定BC、异步在线RL、交替RL及旧demo/actor。默认输入仍是原手柄；显式选择spacepilot才切换。Actor是最终动作发布者，人工输入不是另一个并行遥操作发布进程。

本机完成了新示范采集、两组CUDA BC拟合、BC6148空池RL初始化，并由用户启动了真实在线采集/训练。2026-10-17 23:29:17 +08:00只读快照显示Actor已加载RL2750、Learner更新3367、触觉训练开启、融合层冻结。详细数值保存在[证据快照](../../../evidence/spacepilot_bc_rl_20261017/README.md)，不是最终运行统计，也不是自主成功率验收。

## 人工输入与动作语义

硬件映射及验证见[SpacePilot HIL纪传](../../hardware/evolution/spacepilot-hil.md)。当前键位：Menu接管、数字1开始、ALT成功、Ctrl普通结束；ALT对称键回home，Esc/Ctrl对称键分别闭合/张开夹爪。ID8/2保留跟随/保存标签关系映射，但当前marker功能暂时关闭。

- 夹爪启用，无需按住Menu；review=auto，开合不会触发人工保留/丢弃。夹爪仍不属于六维策略动作。
- 纯人工采集松开Menu后为零动作；在线RL松开后归还策略。after-inference仍按推理完成后的最新输入仲裁。
- 标签跟随、回合外复位不冒充训练动作；跟随边界用control_epoch隔离。
- 训练标签是已接受的命令增量，不是测得的末端位移。

独立工具和新建人工采集共用SpacePilotMapping与MotionSchedule，standalone基准为10mm/s、10°/s；倍率1.5/0.3对应平移合速度上限15mm/s、旋转角速度上限3°/s。SDK换轴和旋转向量转ABC仍只在出口执行一次。

新建standalone人工采集记录足够的动作范围：本批平移逐轴action_scale约0.0015m/次，旋转逐轴约0.010076663rad/次。实际人工旋转再由0.3倍率约束。该动作范围不同于旧手柄数据的0.000577350m/次，不能直接混入旧模型或旧replay。

periodic人工采集/immediate人工接管及回合外调整采用首条有效动作、归零边沿立即发送，连续运动10Hz、不补发积压。在线主setting按用户要求恢复after-inference，不能将其表述为“所有人工动作都不等推理”。

快速边沿可能缩短一条指令或复用观测。所有指令保留审计；对应训练片段需观测递增、指令间隔80–150ms且没有中途外部停止，否则只审计并分段。有效导出记录actual_command_interval_s，不伪造固定100ms训练步。

## 新示范的选择与校验

源目录：`local/rl_episodes/spacepilot_response_20261017_213359`。

| 项目 | 数值 |
| --- | ---: |
| 原始现场回合 | 10 |
| 正常成功 / 正常超时 | 3 / 6 |
| 输入断连异常 | 1，排除 |
| 正常原始回合 | 9 |
| 有效连续片段 / 样本 | 41 / 1499 |
| 非零动作样本 | 1436 |
| 完整历史窗口样本 | 1499 |

用户明确允许正常非成功回合用于BC。只使用通过原命令标签、回执、数组和片段完整性检查的ready数据，未通过审计的边沿片段仍排除。断连原因记录为gamepad disconnected，这是公共输入错误文字，不能据此认定Xbox手柄故障或直接推断硬件根因。

按原始回合划分验证，不能把同一回合的不同片段分进两边：7回合1174样本训练，1成功+1超时共325样本验证。归一化只统计训练回合的有效历史槽，不使用留出数据。BC source manifest与样本哈希在训练读取时核验。

## BC模型与两阶段训练

使用本机CUDA环境 `local/cuda-env/bin/python`，PyTorch 2.14.0+cu130，RTX5060 Laptop GPU。模型是current9stack，两路RGB、触觉和末端状态，六维机械臂动作；视觉ResNet骨干冻结，其余原BC可训练部分参与拟合。

先训练有留出集的初始模型：最多30轮、patience8、batch16、seed7、lr1e-4，实际10轮/740次更新后结束；最佳第2轮/148次更新。验证MSE0.05571396，零动作基线0.06753195，训练均值基线0.06097200。验证集用于选模型，不是独立测试集。

随后两次全量拟合都从该148版本开始，使用相同1499样本、索引、归一化、batch16和seed7：

| 全量拟合 | 粗训练 | 微调 | 粗训最佳MSE | 最终训练MSE | 模型版本 |
| --- | --- | --- | ---: | ---: | ---: |
| 初版 | 1000步，lr1e-4 | 500步，lr1e-5 | 0.00848002 | 0.00576060 | 1648 |
| 当前选用 | 2000步，lr1e-4 | 4000步，lr1e-5 | 0.00576054 | **0.00223588** | **6148** |

微调从本轮粗训最佳权重开始并重建Adam；不是一条连续优化器状态。6148=148+6000，不是训练了6148个episode。初版模型保留，不覆盖。

当前模型相比初版MSE降低61.19%，约改善2.58倍；相比全量拟合前0.03140441约改善14.05倍。9个原始回合误差均下降。63个全零动作标签上，最大绝对预测分量均值从0.18549降至0.10735，仍有残余动作。

最终动作增量MAE：平移约0.05328/0.06800/0.04076mm，旋转约0.01461/0.01360/0.01151°。这些是命令预测误差，不是机器人定位精度。两组最终模型均使用全部正常数据，没有独立验证集。相同样本ID/标签逐项核对；GPU重载最大预测差0；冻结视觉骨干逐张量不变。

| 产物 | 路径 |
| --- | --- |
| BC数据索引/数据审计/训练日志/对比 | `local/rl_training/spacepilot_bc_20261017_213359_index` |
| 留出选择的初始BC | `local/rl_training/spacepilot_bc_20261017_213359_validation` |
| 初版BC1648 | `local/rl_training/spacepilot_bc_20261017_213359_all` |
| 当前BC6148 | `local/rl_training/spacepilot_bc_20261017_213359_2000_4000/actor.pt` |
| 固定BC评估目录 | `local/bc_episodes/spacepilot_response_20261017_213359_eval_2000_4000` |

BC6148文件SHA256：`611afee1d8e3020aebf5269a01b65deb59b8ee49bdaa937851b3058905ea2639`。原始数据和模型位于Git忽略的local目录，不能假定只克隆代码即可复现。

## BC转RL：最终选择旧运行基线

当前活动目录：`local/rl_training/spacepilot_bc6148_rl_legacy_30s_300_20261017`。

用户要求只改明确指定的项目。最终参照Oct11实际会话及旧常用命令，而不是临时建议：weights-only、空Demo/RL、after-inference、batch64、每50次更新发布、每10个有效回合加载、更新预算比例1、探索std0.05/clip0.15、16/20GiB缓存。

保留旧Critic学习率3e-4、Actor学习率1e-5、gamma0.98、tau0.005、Critic:Actor=2:1、图像增强、BC约束权重10和1000次Critic预热。旧夹爪禁用随后被用户明确改为启用；marker随后被用户明确暂时关闭。

指定变化为BC6148、SpacePilot键位与倍率、30秒、跨重启累计300回合、触觉解冻。视觉全部冻结（含历史输入和投影）；融合层按旧设置冻结。前1000次更新整个BC Actor保持不变，之后仅共享触觉CNN由Critic优化器以1e-5训练。Actor头仍由自己的优化器训练，不重复拥有触觉参数。目标网络及固定BC参考不直接梯度训练。

新选项与优化器分组保存到learner.pt，恢复保持；旧checkpoint缺少新选项时保持原全编码器冻结。真实BC6148的CUDA探针验证预热输出差0、触觉更新、视觉与被指定冻结的融合层不变。另一个可选“融合也解冻”的探针通过，但当前主setting没有启用它。

30秒是回合时限，不是成功判据。成功键提前结束并标成功，普通结束/超时不标成功，正常非成功数据仍可入池。累计300按已开始的原始在线回合计数，包含异常中止；不把训练片段当独立回合，不因重启清零。

## 参数文件、初始化与恢复

`hil/run_settings.py`支持 `--parameter`，兼容别名`--settings`。JSON包含prepare、online、environment；主要训练超参数及在线采集参数显式列出，CLI覆盖优先。`--print-settings`只读打印完整解析值、配置哈希及与已有会话的核对结果。

execute/enable-policy必须在命令行显式提供，不能由JSON自动启动控制。时限、数据策略、编码器配置和缓存预算与已初始化任务不符时拒绝；不能仅编辑JSON改变旧checkpoint。初始化和持锁启动分别保存settings_prepare.json、settings_online.json。早期已准备目录另有只读verified快照。

一次修复保留了learner_python的虚拟环境符号链接：不能把`local/cuda-env/bin/python` resolve成系统`/usr/bin/python3.12`，否则丢失pyvenv及CUDA依赖。修复后实际从配置读取的解释器验证CUDA可用。

Ctrl+C应等待保存及CLOSED。下次同一run自动恢复actor.pt、learner.pt、Actor/Critic/target、温度、优化器、计数及磁盘经验索引，不再prepare。cached内存工作集重新填充，不承诺相同驻留成员/采样顺序。未结束回合只保留审计。任务路径指针spacepilot_last_run.txt已补齐，但它不是权重文件。

三种节拍不能混淆：

- Learner满足门槛后持续按batch更新；不是每10回合才训练。
- publish_every=50：每50次Critic更新发布checkpoint。
- reload_every_episodes=10：Actor每新增10个有效保存回合检查新发布权重，回合内不换模型。
- max_updates_per_transition=1：累计预算为1000次预热+新增在线有效transition数，固定历史示范不增加该在线计数。每次更新仍是一个batch，数据可以重复采样。

## Marker功能及隔离边界

tag10/tag12检测、保存相对位姿及恢复默认关系的链路存在，ID2保存、ID8跟随/停止，文件及X/Z标定已只读校验。但当前参数no_tag_follow=true，不创建TagFollowSession及其额外相机订阅/检测线程；ID8/2暂不执行。RL视觉输入继续使用相机。

现有启用实现只部分隔离：后台检测不阻塞等待，但图像转换/同步保存仍在Actor路径，退出会等待检测线程；跟随失效或到达HOLDING时仍保持跟随状态、暂停策略和回合时钟。120ms新鲜度从本机回调算起，不证明上游端到端帧龄。严重未捕获异常仍可能中止Actor并关闭Learner。

后续讨论方案是独立Marker节点，经请求/状态/候选topic联系，Actor仍唯一发布最终动作；超时/旧候选不执行、故障不自动切回策略运动。**独立节点迁移、硬超时隔离和数字3功能总开关均未实施。** 当前只用了现有配置开关暂时关闭。

## 现场快照与下一步

23:29:17只读快照：50个已结束原始审计回合（成功标记37、超时11、输入断连1、普通结束1），49个training_ready，导出9308条transition；Actor有效完成49、加载2750，Learner更新3367、已发布3350。catalog_online=9308、catalog_interventions=4839、catalog_seed=0。不同文件顺序读取，数值不是事务一致的最终统计。

日志中的tactile_encoder_trainable=true、fusion_layer_trainable=false，与配置和CUDA探针一致。在线回合可含人工接管，37个成功标记不能解释为37次BC/RL自主成功。单批Critic loss和BC漂移也不能单独说明策略变好。

下一步先检查自主/人工占比、成功奖励覆盖、触觉变化及停止行为；marker继续关闭，另行实现节点隔离后再做独立恢复位姿验证。SDK目标提交与停止拖尾的早期证据仍有效，本轮没有修改底层停止策略。
