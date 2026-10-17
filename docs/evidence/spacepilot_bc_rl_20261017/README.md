# 2026-10-17 SpacePilot、BC6148与在线RL证据快照

采集时间：**2026-10-17 23:29:17.147937 +08:00**。读取运行中的JSON文件，不调用ROS服务、不发机器人命令、不暂停Actor/Learner。文件逐个读取，不是事务一致快照或最终运行汇总。

## 文件

| 文件 | 内容 |
| --- | --- |
| [snapshot.json](snapshot.json) | 当前setting、启动时实际参数、初始化报告、Actor/Learner状态、逐回合审计摘要、BC数据审计和两组训练对比，以及各源文件哈希/mtime |
| [settings.json](settings.json) | 捕获时的主参数文件；启动快照中的document与它相同 |
| [buttons.json](buttons.json) | 本机已选择的九键SpacePilot配置副本 |
| [SHA256SUMS](SHA256SUMS) | 本证据包各文件的SHA256 |

## 本次读取的关键数值

- BC来源10个回合：3成功、6超时、1断连异常；保留9回合/41片段/1499样本。
- BC1648训练MSE0.00576060498；BC6148训练MSE0.00223588035；下降61.19%，同一批样本上改善约2.58倍。
- BC6148两阶段6000更新，模型文件SHA256为`611afee1d8e3020aebf5269a01b65deb59b8ee49bdaa937851b3058905ea2639`；保存重载预测最大差0。
- 当前在线run：`local/rl_training/spacepilot_bc6148_rl_legacy_30s_300_20261017`，weights-only、初始seed0、30秒、累计上限300、触觉训练/融合冻结。
- Actor：WAIT_START，49个有效完成回合，实际加载2750，最近检查点为40回合。
- Learner：TRAINING，更新3367，已发布3350；预算10308；tactile_encoder_trainable=true，fusion_layer_trainable=false。
- 原始结束审计50份：success37、timeout11、gamepad disconnected1、manual_stop1；49份可训练，导出9308条。
- replay磁盘登记online9308、interventions4839、seed0。Demo/RL共享人工数据，不能将两池条数加成独立样本总量。
- 实际生效：after-inference，publish50、reload10、预算比例1，CUDA Actor/Learner，夹爪开启、marker关闭。

37个成功是允许人工接管的回合结果标记，不是37次自主策略成功。BC误差是同数据拟合结果，不是独立泛化或机械臂定位误差。文件捕获后训练继续运行，因此不能用这份快照断言当前实时数值。

源文件哈希用于标明“当时读到的字节”，不要求运行中的源JSON以后继续保持同一哈希。source mtime在读取后记录，不能用它建立跨文件原子一致性。

代码HEAD为eb8e3b8，捕获时包含后续未提交实现；HEAD本身不涵盖所有运行功能。本次仅整理文档，不自动提交或推送。

## 使用与校验

```bash
cd /home/zhoutong/omi_folder/omi_proj/docs/evidence/spacepilot_bc_rl_20261017
sha256sum -c SHA256SUMS
```

最新参数及命令看[操作教程](../../../tutorials/spacepilot_bc6148_online_rl.md)，专题现状看[纪传体](../../agent/training/evolution/spacepilot-bc-online-rl.md)，过程看[编年体](../../agent/training/chronicles/2026-10-17-spacepilot-bc-online-rl.md)。这里只保存小型证据，不包含原始图像、全部经验或权重；迁移机器必须另行携带local数据及模型。
