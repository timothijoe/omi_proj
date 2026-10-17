# SpacePilot BC6148 在线 RL：显式 setting 与旧配置对照

`--parameter`与原`--settings`完全等价，均显式加载同一JSON；下文统一使用`--parameter`。

当前唯一主配置：[configs/spacepilot_bc6148_online_rl.json](../configs/spacepilot_bc6148_online_rl.json)。初始化和在线运行均必须在使用命令中显式传 `--parameter`；老CLI接口保留兼容，但本流程不依赖省略参数后的默认值。

## 基线与允许的变化

基线是本机旧任务 `local/rl_training/bc12045_newdata_30s_20261011_01` 的初始化报告、checkpoint超参数、Actor状态，以及提交521fd47的常用命令D2/D4。旧任务实际时限为45秒，目录名中的30s不代表当时实际配置。

| 项目 | 旧配置 | 当前setting |
| --- | --- | --- |
| BC来源 | BC12045 | BC6148（本轮选定） |
| 初始化数据 | weights-only，空Demo/RL池 | 保持；不导入1499条历史示范 |
| 单回合时限 | 实际45秒 | 30秒（用户指定） |
| 累计回合上限 | 未设置跨重启上限 | 300（用户指定） |
| 人工输入 | 原手柄 | 本轮确认的SpacePilot键位 |
| 人工倍率 | 原输入配置 | 平移1.5、旋转0.3；standalone方案 |
| 视觉编码器 | 冻结 | 保持；包含历史输入及视觉投影 |
| 融合层 | 冻结 | 保持；撤回此前助手建议的解冻 |
| 触觉编码器 | 冻结 | 1000次Critic预热后解冻（用户指定） |
| 触觉学习率 | 不训练 | 1e-5（新增可训练分支的显式设置） |
| Critic预热 | 1000次更新 | 保持 |
| Critic / Actor学习率 | 3e-4 / 1e-5 | 保持 |
| discount / target tau | 0.98 / 0.005 | 保持 |
| Critic:Actor更新比例 | 2:1 | 保持 |
| 图像增强 / BC约束权重 | 开启 / 10 | 保持 |
| batch / Demo及在线门槛 | 64 / 各100条 | 保持 |
| 权重发布 / Actor加载 | 50次更新 / 10个有效回合 | 保持 |
| 更新预算比例 | 每条新增在线transition对应1次更新预算 | 保持 |
| 仲裁模式 | after-inference | 保持；撤回此前助手建议的immediate |
| 策略探索噪声std / clip | 0.05 / 0.15 | 保持，仅作用于策略 |
| 经验缓存目标 / 管理上限 | 16 / 20 GiB | 保持 |
| 夹爪控制 | no-gripper | 用户明确要求启用，online.no_gripper=false |
| 标签跟随 | 开启 | 用户暂时关闭：online.no_tag_follow=true；ID8/2映射保留 |
| ROS | domain13，非localhost-only，SUBNET | 保持，写入environment |

此前助手准备的 `spacepilot_bc6148_rl_tactile_fusion_30s_300_20261017` 是“预加载示范、融合解冻、immediate”的另一份任务，不再由主setting选用；原文件保留。当前任务是新的空池初始化，不改写旧checkpoint。

## 配置文件分区

- `prepare`：BC来源、目标目录、是否导入示范、回合时限与累计上限、冻结/解冻、学习率、SAC超参数、经验池配置。
- `online`：同一目标目录、Actor/Learner设备、batch、发布/加载节拍、训练门槛与预算、仲裁和探索、回合数量、输入映射/速度、传感器帧龄门槛、夹爪与标签跟随参数。
- `environment`：ROS domain与发现设置。实际运行时显式应用；print-settings只展示。

路径相对于项目根目录。执行使能`--execute --enable-policy`只允许在命令行显式提供，不由JSON自动开启。运行参数的命令行覆盖优先；初始化固化的参数若与会话不符，会在启动前报错，不能只改JSON就更改已有模型/经验池。

## 当前已准备好的新任务

```text
local/rl_training/spacepilot_bc6148_rl_legacy_30s_300_20261017
```

已从BC6148完整复制Actor与归一化，RL更新计数从0开始；初始Demo=0、在线=0。原BC训练数据仍保留在原目录，未删除。

空池意味着必须先取得本任务的新人工接管数据。有效人工transition同时计入Demo和在线池；建议先用Menu接管完成若干回合，直到新Demo与在线样本各达到100。只有策略样本时，Learner会等待人工示范；这不是加载BC失败。

## 只读显式加载核对

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/prepare_bc_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --print-settings
bash scripts/run_async_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --print-settings
```

打印 `SETTINGS_LOADED`（完整实际参数、环境与源文件SHA256）、`SESSION_SETTINGS_EXPECTED` 和 `SESSION_SETTINGS_VERIFIED`。两条命令不启动机器人或训练。

## 在线 RL 运行，包含策略采集与人工接管

当前会话已经准备好，直接运行这一段；不要对同一路径再prepare。接收端和传感器沿用现场已验证配置，退出其他动作发送入口。

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/run_async_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --execute \
  --enable-policy
```

配置文件已经指定ROS_DOMAIN_ID=13、ROS_LOCALHOST_ONLY=0、ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET。

数字1开始；Menu按住人工接管、松开交还策略；ALT成功、Ctrl普通结束；26回合外回home。当前按用户要求暂时禁用marker检测、相对位姿保存和跟随，不创建TagFollowSession及其图像订阅/检测线程，ID8/2暂不执行动作，既有默认位姿文件保留。后续将online.no_tag_follow改回false并重启即可重新测试。RL自身的视觉观测仍正常使用相机。

用户已明确启用夹爪：Esc左右对称键（ID28）闭合，Ctrl左右对称键（ID27）张开，无需按住Menu。保持review=auto，夹爪键不会触发人工保留/丢弃。夹爪指令仍不属于六维机械臂策略动作。

夹爪设置在下次启动加载生效；若进程已运行，先正常退出后用相同setting重启，不需要重新prepare。其余旧参数及已确认的变化保持不变。

30秒是回合时限，超时不自动成功。标签功能当前关闭；以后重新启用时，跟随仍按旧逻辑暂停回合计时，总墙钟时间可能更长。累计300是已开始的在线回合上限，包含异常中断的已开始回合；跨重启扣除历史数量，示范片段不计入。online.episodes=300是本次进程最多尝试数量，实际取它与累计剩余额度的较小值。

## 重新从BC初始化另一份新任务

```bash
cd /home/zhoutong/omi_folder/omi_proj
run_dir="local/rl_training/spacepilot_bc6148_rl_$(date +%Y%m%d_%H%M%S)"
bash scripts/prepare_bc_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --run "$run_dir"
```

初始化完成后，在同一终端启动时也显式指定该新目录：

```bash
bash scripts/run_async_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --run "$run_dir" \
  --execute --enable-policy
```

初始化会保存settings_prepare.json；在线启动取得任务锁后保存settings_online.json，记录配置全文、SHA256、命令行覆盖后的实际值及本次剩余回合额度。只读预览不写这两份运行快照。

## Ctrl+C后恢复权重和数据

运行中按一次Ctrl+C，等待保存、Learner退出及CLOSED提示后再关闭终端。正常退出保存actor.pt、learner.pt及经验目录；中断的未完成回合只保留审计，不伪装成成功或完整训练数据。若出现LEARNER_KILLED或写盘错误，先检查日志，不能当作正常保存成功。

续跑不调用prepare、不重新生成时间戳目录，也不使用--resume（该在线入口没有这个参数）。指定原run目录即可自动恢复Actor/Critic/target、优化器、温度、训练计数和经验索引，缓存从已保存数据重新填充。回合上限继续按累计300计算。采集中的物理位置不会自动恢复。

新任务一条完整流程（初始化成功后才记录目录并启动）：

```bash
cd /home/zhoutong/omi_folder/omi_proj
run_dir="local/rl_training/spacepilot_bc6148_rl_$(date +%Y%m%d_%H%M%S)"
bash scripts/prepare_bc_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --run "$run_dir" &&
printf '%s\n' "$run_dir" > local/rl_training/spacepilot_last_run.txt &&
bash scripts/run_async_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --run "$run_dir" \
  --execute --enable-policy
```

重开终端后，用上述流程记录的路径续跑：

```bash
cd /home/zhoutong/omi_folder/omi_proj
run_dir="$(cat local/rl_training/spacepilot_last_run.txt)" &&
bash scripts/run_async_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --run "$run_dir" \
  --execute --enable-policy
```

也可以直接把--run写成实际旧目录。spacepilot_last_run.txt只是方便记住最近一次使用该流程创建的任务，不是模型权重；同一时间只运行一个动作入口。

## 训练与采集的三个节拍

1. Learner满足数据门槛后在后台按batch训练，不是等10个episode才训练。
2. publish_every=50：每50次Critic更新发布新权重。
3. reload_every_episodes=10：Actor每完成10个有效保存回合检查新权重；没有新版本就继续旧模型，回合中不切换。

max_updates_per_transition=1控制累计预算：`1000次Critic预热 + floor(新增在线有效transition数×1)`。例如新增200条，累计上限1200次Critic更新。每次更新是一个64条的batch，可反复采样。达到预算后Learner等待新数据，Actor不因此停采。

前1000次Critic预热保持整个BC Actor不变，之后仅触觉卷积编码器参与共享编码器更新；视觉与融合层持续冻结。Actor头按原2:1节拍更新。在线after-inference保留推理完成后仲裁，不能声称它等同独立遥操作的即时响应；纯人工采集入口的新响应机制不受本RL setting改变。

## 验证

旧SAC/BC及经验池流程的回归保持通过。选择性训练用真实BC6148在CUDA上验证：预热不改变BC输出，之后触觉参数确实更新，视觉保持逐项一致；融合冻结和融合解冻两种可选配置均有独立检查。默认主setting只选择触觉解冻。没有自动启动现场RL或机器人动作。

用户随后已启动本任务。2026-10-17 23:29:17只读快照显示Actor2750、Learner3367，50份结束审计、49个有效完成回合；完整数值及语义见[当天编年](../docs/agent/training/chronicles/2026-10-17-spacepilot-bc-online-rl.md)与[证据包](../docs/evidence/spacepilot_bc_rl_20261017/README.md)。这些是运行中快照，不是最终结果或自主成功率。

## 对应监控网页

另开终端：

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/view_training_monitor.sh \
  --run local/rl_training/spacepilot_bc6148_rl_legacy_30s_300_20261017 \
  --port 8768
```

打开 http://127.0.0.1:8768/ 。如果使用自己新建的run，监控的--run也要替换为该实际目录。监控只读，关闭网页/监控进程不结束训练；端口占用可另指定一个端口。指标与实时/历史状态解释见[监控教程](training_monitor.md)。
