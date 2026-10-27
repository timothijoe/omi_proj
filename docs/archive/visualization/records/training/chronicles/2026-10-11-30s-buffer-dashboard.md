> 历史资料：原路径 `docs/agent/training/chronicles/2026-10-11-30s-buffer-dashboard.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../../../modules/visualization.md)；本页保留原过程与证据。

# 2026-10-11：原BC权重、新数据目录、30秒回合与双池可视化

后续：用户已要求再次清空并将时限改为45秒，目录名称保持不变；下面的首次30秒准备记录为历史记录。
启动命令仍可沿用，实际配置及归档见[最新重置记录](../../../../replay/records/training/chronicles/2026-10-11-invalid-data-reset.md#第二次清空并改为45秒1843)。

用户要求保留原BC checkpoint作为初始化，只使用新数据，新回合时限约30秒，
并可视化两个buffer存量及成功/timeout/失败数量。

已准备 `local/rl_training/bc12045_newdata_30s_20261011_01/`，原BC12045张量逐项一致，
Demo/RL为空、没有历史来源；助手未启动本会话的机器人或Learner。
`weights_only_validation.json`记录实际BC校验、空SQLite目录、模型加载与统一30秒契约检查。
旧BC本身的20秒配置未改动。

新增准备参数 `--episode-seconds 30`，仅允许与 `--weights-only` 同用：
显式创建新会话的config、Actor/Learner checkpoint、session和replay契约，保留源contract作为provenance。
不会放宽正常checkpoint恢复时的契约一致性检查，也不会把旧时限的数据直接混入新契约。

已执行的准备命令（本目录不重复执行）：

```bash
bash scripts/prepare_bc_rl.sh \
  --bc-run local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --run local/rl_training/bc12045_newdata_30s_20261011_01 \
  --weights-only --episode-seconds 30 --replay-backend cached \
  --cache-target-gib 16 --cache-limit-gib 20 --critic-warmup-updates 1000
```

用户启动/续跑命令（旧动作发送端需先正常退出，传感器和接收端沿用）：

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
bash scripts/run_async_rl.sh \
  --run local/rl_training/bc12045_newdata_30s_20261011_01 \
  --actor-device cuda --learner-device cuda \
  --batch-size 2 --publish-every 50 \
  --reload-every-episodes 10 \
  --min-online 100 --min-demo 100 \
  --max-updates-per-transition 1 \
  --arbitration-mode after-inference \
  --exploration-noise-std 0.05 --exploration-noise-clip 0.15 \
  --no-gripper --execute --enable-policy
```

需要本批至少100条有效人工接管transition并结束回合保存，才满足Demo启动门槛。
Actor可以先采集；Learner不会用策略数据冒充人工Demo。新数据中的人工记录同时属于Demo/RL，底层共享。
初次加载原BC，后续续跑会加载本会话的最新权重；运行中每新增10个有效回合检查更新。

## 新版网页

已为新会话启动只读服务 http://127.0.0.1:8771/ 。服务正在运行时不要重复占用同一端口。
以后重启命令：

```bash
bash scripts/view_training_monitor.sh \
  --run local/rl_training/bc12045_newdata_30s_20261011_01 --port 8771
```

新增首页两组卡片：

- Demo/RL分别显示内存可采样条数、磁盘登记条数；显示独立驻留样本、共享管线内存/上限、30秒时限。
  未收到Learner遥测时标为“初始登记”，不把登记条数当作真实内存驻留；关闭后标明最近快照。
- 本会话回合统计：已结束、人工标记成功、timeout、人工提前结束、失败/异常、进行中/暂存。
  结果分布条与人工标记成功率，点击卡片进入对应回合筛选。

统计按本目录原始回合计数，不按导出的segment重复计数，也不汇总外部历史来源。
timeout和人工提前结束单列；“失败/异常”是其余有明确异常原因的已结束回合，原因未知另记。
“未成功”合计包含timeout/人工结束/异常/未知；暂存不推断成失败。成功率是人工标记成功/已结束回合，
不等同于自主成功率。两池共享人工样本，因此不能把两池条数之和当作独立经验数。

## 验证

相关回归65 passed、1 skipped；包括30秒契约传递、原权重不变、空池等待和新数据训练，
以及回合分类不重叠、暂存不算失败、驻留/磁盘口径与共享数据计数。
Playwright检查桌面1440×1100、窄屏390×844，五类卡片筛选、buffer数字与30秒显示通过，无JS异常或横向溢出；
截图已人工查看。浏览器分类测试使用合成fixture，不代表实际回合结果。
证据在 `local/diagnostics/monitor_buffers_30s_20261011/`，临时fixture服务已关闭。
实际新会话8771的API确认Demo/RL初始登记0、回合0、时限30秒。
