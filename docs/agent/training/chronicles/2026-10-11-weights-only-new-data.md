# 2026-10-11：只继承BC权重，全部训练数据从新会话采集

用户明确：原始BC初始化模型可以沿用，但旧人工Demo和旧RL数据都不能用于新会话训练。
此前仅去掉 `--recorded-source` 的命令仍会导入1387条旧Demo，不满足这一要求。

## 本次完成

`prepare_bc_rl.sh` 新增 `--weights-only`：

- 只读取原BC的Actor、config和模型内的recipe/归一化；完整Actor与原BC逐张量一致。
- 不读取原 `dataset.json` 或任何旧示范/录制数据。新 `dataset.json` 的episodes为空。
- Demo、RL与固定seed计数全部为0，cached目录和外部sources列表均为空。
- 必须使用cached后端；不能同时传 `--recorded-source`，冲突在创建目录前报错。
- 新人工接管transition属于新会话，进入Demo和RL两个采样索引，底层共享一份数据；新策略动作只进入RL。
- BC参考模型继续来自原BC权重；BC损失的人工动作标签只来自新采集的数据。

Actor原来加载时必须读取首条旧Demo作为数值探针，这一依赖也已移除。
此模式优先使用当前实时观测做加载检查；尚无实时观测时仅用符合输入形状的零值张量预热并检查输出有限性。
该数值探针不会入池、不发布动作，不代表真实传感器已就绪；实际控制仍经过原来的观测和回执门控。
旧会话保留其原有加载方式。已有空池不能运行依赖seed录制的 `--probe-only` 并发验证，会明确报错。

## 已准备的新会话

`local/rl_training/bc12045_newdata_only_20261011_01/` 已创建，尚未由本次操作启动机器人或Learner。
来源为原BC12045，RL更新计数0，Demo=0、RL=0、固定seed=0，不是从之前的RL4777续训。
`bc_initialization.json` 和 `weights_only_validation.json` 保存核验结果。

以下准备命令已执行，仅供追溯，不要再次对同一目录初始化：

```bash
bash scripts/prepare_bc_rl.sh \
  --bc-run local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --run local/rl_training/bc12045_newdata_only_20261011_01 \
  --weights-only --replay-backend cached \
  --cache-target-gib 16 --cache-limit-gib 20 \
  --critic-warmup-updates 1000
```

## 启动命令

正常退出旧的动作发送入口；接收端和传感器沿用现场配置，然后执行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

bash scripts/run_async_rl.sh \
  --run local/rl_training/bc12045_newdata_only_20261011_01 \
  --actor-device cuda --learner-device cuda \
  --batch-size 2 --publish-every 50 \
  --reload-every-episodes 10 \
  --min-online 100 --min-demo 100 \
  --max-updates-per-transition 1 \
  --arbitration-mode after-inference \
  --exploration-noise-std 0.05 --exploration-noise-clip 0.15 \
  --no-gripper --execute --enable-policy
```

本命令主动设置两个门槛均100。先完成一段含至少100条有效人工接管transition的新回合，
让Demo达到门槛；这些人工记录也计入RL。仅有策略数据不能替代人工Demo，Learner会等待，属于预期行为。
回合需结束并保存入池，回合中原始记录不会立即变成可采样训练transition。
Demo就绪后前1000次仅Critic预热；两池门槛满足后进入正常混合训练并更新Actor。
Actor可在Learner等待期间继续从BC策略采集；每新增10个有效回合检查新权重。
以后续跑只重复启动命令，不重复准备；这批会话中的已有数据仍保留并继续使用。

网页另开终端，指向新的会话：

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/view_training_monitor.sh \
  --run local/rl_training/bc12045_newdata_only_20261011_01 --port 8770
```

打开 http://127.0.0.1:8770/ 。新原始数据、缓存目录与模型均保存于该会话，不修改旧会话。

## 验证

相关回归53 passed、1 skipped。新测试在BC目录完全没有dataset或示范文件时准备成功、Actor能加载；
空池及仅新策略数据时Learner不更新，加入新人工回合后完成预热/Actor更新；所有索引均属于新会话，seed仍为0。
历史来源参数冲突在创建目录前拒绝。

真实BC12045准备与CPU数值探针验证通过：Actor逐张量一致，输出有限且在界内；
SQLite records=0、sources=0，manifest外部sources为空。该验证不使用录制观测，也不发布机器人动作。

相关：[探索噪声与换权重](2026-10-11-online-exploration.md)、[缓存机制](../evolution/cached-replay.md)。
