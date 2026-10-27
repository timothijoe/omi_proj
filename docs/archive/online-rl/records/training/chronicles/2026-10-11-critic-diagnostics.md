> 历史资料：原路径 `docs/agent/training/chronicles/2026-10-11-critic-diagnostics.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../../../modules/online-rl.md)；本页保留原过程与证据。

# 2026-10-11：Critic负Q与稀疏成功监督的离线诊断

承接[首轮实验](../../../../replay/records/training/chronicles/2026-10-11-cached-offline-exp01.md)，本轮补齐实际训练批次的奖励、Q、目标Q和TD误差日志。
夹爪按闭合假设处理；没有启动机器人、覆盖原BC或更改奖励、归一化、Demo/RL采样比例。

## 已验证的实现与数据

`hil/networks.py` 的Critic更新仍为 `r + 0.98 * (1-done) * min(target_Q1,target_Q2)`，
没有在backup中减熵；本次仅增加从同一实际批次提取诊断数值，不增加模型前向或额外抽样。

- 记录优化前的双Q均值/范围、目标值均值/范围、负目标数、TD绝对误差、正奖励与终止命中数。
- `positive_q_mean`、`terminal_target_mean` 只在对应样本存在时出现，缺席不表示0。
- 实验脚本逐步保存日志，并在初始化、预热结束和最终模型上评估同一留出集。
- 中间评估保存/恢复Torch随机数状态，不推进训练的随机动作/图像增强序列。
- 分析测试构造不同的在线双Q与target双Q，验证成功目标精确为+1，非终止零奖励目标正确保留bootstrap。

真实训练目录中没有负奖励，奖励与终止计数一致：

| 来源 | transition数 | 正奖励/成功终止数 |
| --- | ---: | ---: |
| 初始人工示范 | 1387 | 5 |
| 新训练人工动作 | 1955 | 0 |
| 新训练策略动作 | 1088 | 6 |

“策略动作带成功奖励”指标签落在实际最后一条策略动作上，不表示回合全程自主成功。
Demo池共有3342条，其中5条直接正奖励；按batch2均匀预热1000步，期望命中约2.99次。

## exp02：保持首轮参数，测量实际命中

目录：`local/experiments/cached_rl_exp02_q_diagnostics_20261011/`。
仍从原BC12045重新初始化Critic，1000次预热＋200次混合更新，100次Actor更新。
按相同split seed=11留出3个完整原始回合，16个训练回合；留出536条，其中318条人工动作。

| 阶段 | Critic更新 | 抽样条次 | 直接正奖励命中 | 负训练目标 |
| --- | ---: | ---: | ---: | ---: |
| Demo-only预热 | 1000 | 2000 | 3 | 1997 |
| Demo/RL混合 | 200 | 400 | 1 | 399 |

正奖励实际命中更新251、311、498、1021；全部为成功终止，目标精确为+1。
命中计数包含重复抽样，不能解释为见到了4个不同成功回合。

| 留出指标 | 初始化 | 预热结束 | 最终 |
| --- | ---: | ---: | ---: |
| 人工动作MSE | 0.208583 | 0.208583 | 0.182503 |
| 记录动作的双Q均值 | -0.575155 | -1.028854 | -0.937829 |
| 两个成功终止样本的双Q均值 | -0.498912 | -0.984373 | -0.896700 |

初始化已经偏负；预热后仍未修正。最后100步的平均Critic loss约0.008678，
但训练目标均值仍约-0.959674，说明小TD误差只表示拟合当前bootstrap目标，并不证明价值已校准。
人工动作MSE降低约12.50%，与首轮接近；Actor含BC约束，这个结果不能单独归因于有效RL价值学习。

已完成1200次Critic、100次Actor更新；受管内存峰值9.442 GiB，无淘汰；耗时183.69秒。
原始11257个文件SHA-256与编码器张量保持一致，留出回合未入训练索引。
`report.json.critic_diagnostics` 保存分阶段汇总，`training_progress.jsonl` 保存全部1200步。
`reward_catalog.json` 是结束后只读查询得到的来源奖励统计。

## exp03：只延长Critic预热

目录：`local/experiments/cached_rl_exp03_warmup4000_20261011/`。
预热由1000改为4000，随后仍为200次混合更新、100次Actor更新；其余配置沿用exp02。
两个实验的完整数据划分、源文件哈希及初始化探针数组完全相同。
事后比对前1000步的Critic loss、Q、目标Q、TD误差和奖励命中字段，1000行全部逐值一致。
证据保存在exp03的 `comparison_with_exp02.json`。

| 指标 | exp02：1000预热 | exp03：4000预热 |
| --- | ---: | ---: |
| 预热抽样条次 | 2000 | 8000 |
| 预热正奖励命中 | 3 | 8 |
| 后续200次更新正奖励命中 | 1 | 1 |
| 预热结束留出Q均值 | -1.028854 | -0.747129 |
| 最终留出Q均值 | -0.937829 | -0.612231 |
| 最终留出成功终止Q均值 | -0.896700 | -0.579658 |
| 最终人工动作MSE | 0.182503 | 0.186497 |
| 相对原BC的MSE下降 | 12.50% | 10.59% |
| 受管内存峰值 | 9.442 GiB | 9.442 GiB |
| 全流程耗时 | 183.69秒 | 349.53秒 |

exp03的8000条预热抽样中7992条目标为负；8次成功命中的终止目标均为+1。
最后一次预热正奖励在第2583步，此后连续1417次预热更新没有直接正奖励。
最终536条留出记录的双Q均值范围仍为-0.790272至-0.379285；两个成功终止样本也仍被低估。

exp03累计4200次Critic、100次Actor更新，正常结束；4430条独立训练经历全部驻留，未发生淘汰。
来源11257个文件哈希不变、编码器不变、留出未登记进训练；Actor权重仅存实验目录，没有部署。

本轮结论：延长均匀预热部分减轻了负Q，但没有解决成功终止价值估计，动作MSE也未优于1000步组。
因此不把4000步设为新默认，也不把任何实验权重宣称为优于BC的真机策略。
已确认正奖励没有被取反或漏掉终止掩码；直接成功监督稀疏、随机初始化偏负与bootstrap传播是当前
证据支持的诊断方向，尚未分别隔离它们的贡献。

下一项有依据的对照是：在维持Demo/RL两池比例与人工BC标签语义的前提下，
实验性增加成功终止/成功末段被Critic抽到的频率，并单独评估终止样本误差及留出动作漂移。
本轮没有引入该采样策略，也没有改写现有奖励；需要对其采样偏置及小样本过拟合单独验证。

## 验证与复现

回归：91 passed、2 skipped。CUDA专用测试在普通沙箱跳过；真实GPU训练经单独批准执行。
第一次在CUDA轻量环境跑完整回归，3项因缺少Pillow失败；随后使用项目完整 `.venv` 重跑全组通过。
关闭pytest插件自动加载以避免系统ROS插件引入无关依赖。

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_protected_rl.py tests/test_serl_alignment.py tests/test_cached_replay.py \
  tests/test_dual_replay.py tests/test_async_training.py tests/test_training_monitor.py \
  tests/test_hil_runtime.py tests/test_offline_rl_pipeline.py

local/cuda-env/bin/python -u scripts/run_cached_offline_experiment.py \
  --bc-run local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --output local/experiments/cached_rl_exp02_q_diagnostics_20261011 \
  --updates 1200 --warmup 1000 --batch-size 2 \
  --cache-target-gib 16 --cache-limit-gib 20 --device cuda --diagnose-q
```

exp03使用同一命令，将output改为 `local/experiments/cached_rl_exp03_warmup4000_20261011`，
将 `--updates` 改为4200、`--warmup` 改为4000。

重跑必须换新的output目录。该脚本只读原始来源，所有新模型均为离线实验权重。
当前结论来自单一随机种子与同一小型留出集；后台预取的执行时序也可能造成抽样序列差别，不宣称逐位复现。
