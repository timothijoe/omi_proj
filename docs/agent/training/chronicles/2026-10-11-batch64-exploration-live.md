# 2026-10-11：batch64在线训练与探索噪声现场核验

用户决定先使用batch size 64现场测试，不继续做2/32/64/128容量对照。
本次只读核对运行状态和已经保存的动作记录，没有修改参数、暂停训练或发布机器人动作。

## 当前会话与参数

活动目录：`local/rl_training/bc12045_newdata_30s_20261011_01/`。
目录名中的30s是历史名称，实际 `config.json` 中回合时限为 **45秒**。
该路径已按用户要求两次归档重建，最新一次恢复原BC12045权重、空Demo/RL，随后由用户开始新采集。
本批训练仅使用本会话重建后采集的数据，不导入旧Demo、旧RL经历或归档数据。

| 项目 | 已核对的设置 |
| --- | --- |
| Learner batch size | 64 |
| 正常训练批次 | Demo/RL各半；人工BC约束另从Demo抽样 |
| Critic预热 | 前1000次更新，使用本批新Demo |
| 探索模式 | clipped_gaussian，归一化动作tanh之后加噪声 |
| 噪声标准差 | 0.05 |
| 每轴噪声绝对上限 | 0.15，最终动作再限幅到[-1,1] |
| 人工接管 | 不加探索噪声 |
| 网页 | http://127.0.0.1:8771/ |

当前使用的启动参数如下；这是用户已运行命令的记录，不应另开第二套同时执行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
bash scripts/run_async_rl.sh \
  --run local/rl_training/bc12045_newdata_30s_20261011_01 \
  --actor-device cuda --learner-device cuda \
  --batch-size 64 --publish-every 50 \
  --reload-every-episodes 10 \
  --min-online 100 --min-demo 100 \
  --max-updates-per-transition 1 \
  --arbitration-mode after-inference \
  --exploration-noise-std 0.05 --exploration-noise-clip 0.15 \
  --no-gripper --execute --enable-policy
```

## 实际运行快照

首次回应用户噪声确认时，Actor为ACTIVE、版本0；Learner为TRAINING、batch64、更新193。
整理文档时再次核对，时间为 **2026-10-11 18:52:35，Asia/Shanghai**：

- Actor为SAVING，记录已完成3个有效回合，仍使用版本0。
- Learner为TRAINING，batch size 64，Critic更新612，最近发布版本600。
- 当前进程Actor更新次数为0，符合尚在1000次Critic预热阶段的设置。
- Actor遥测明确包含 `mode=clipped_gaussian`、`std=0.05`、`clip=0.15`、`policy_only=true`。

这是运行中的相邻文件快照，不是最终回合数或最终模型效果。发布版本增长在预热期间不表示Actor参数已变化。

## 已保存动作的证据

检查回合 `74e8745766694ef78eced41ce607534c`，读取原始动作NPZ的metadata：

- `000189.npz`：`action_source=policy`、`gate=policy`，exploration字段包含非零噪声。
  例如归一化dz从原策略 **0.40261221** 加噪声 **-0.09078592** 后变成 **0.31182629**。
  dx从-0.96359378加入-0.04847926噪声后触及最终动作下界，实际保存为-1；
  因此记录同时区分 `clipped_noise` 与真正施加的 `applied_delta`。
- `000213.npz`：`action_source=human`、`gate=human`，`exploration=null`。
- 六轴均核对 `mean_action + applied_delta == normalized_action`（浮点误差容限1e-7），
  并核对噪声上限。说明噪声已实际进入策略命令记录，而人工接管旁路未被加噪声。

上述证据确认在线命令路径与存储标签已经启用探索；不据此推断噪声提高了任务成功率或实际末端位移。

## batch容量结论的边界

只读显卡检查显示RTX 5060 Laptop、8151 MiB显存；该检查时显存占用2213 MiB、空闲5471 MiB，
这是当时的瞬时读数，不是batch64训练时的显存峰值。
容量对照脚本已准备，但用户要求不继续测试，未取得各batch的对照报告。
目前能够确认batch64已实际执行训练更新；未对64/128的吞吐、峰值显存、与Actor并发的延迟或长期稳定性作出验证结论。

相关：[探索实现与换权重](2026-10-11-online-exploration.md)、
[归档重建与45秒配置](2026-10-11-invalid-data-reset.md)、
[双池与回合统计网页](2026-10-11-30s-buffer-dashboard.md)。
