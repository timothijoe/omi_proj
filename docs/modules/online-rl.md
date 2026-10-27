# 在线RL与权重交接

Actor负责输入、仲裁、动作发布和回合记录，独立Learner消费经验并更新策略；传感器、接收端和网页单独运行。
实现入口为[async_training.py](../../src/omi_hil_rl/hil/async_training.py)、[learner.py](../../src/omi_hil_rl/hil/learner.py)。
主维护入口是`run_async_rl.sh`／`collect_rl_episodes.sh`，训练网页需单独启动并选择同一run。

## 配置与任务选择

选定JSON是[spacepilot_bc6148_online_rl.json](../../configs/spacepilot_bc6148_online_rl.json)。`--parameter`与`--settings`等价，
CLI覆盖优先；`--execute --enable-policy`只在命令行显式开启。初始化契约与运行配置冲突会拒绝启动。
打印参数用`--print-settings`，完整操作见[SpacePilot在线教程](../../tutorials/spacepilot_bc6148_online_rl.md)。

原BC6148到新任务为weights-only：继承Actor与归一化，建立新Critic／优化器／计数和空池，不导入1499条原始示范。
已有run自动恢复，不用`--resume`、不重新prepare；恢复磁盘索引并重建RAM工作集，不保证抽样位级复现。
任意RL checkpoint另起空池的通用入口仍未实现，不能只拷贝actor.pt冒充完整恢复。

主JSON默认指向10月17日旧run。10月24日最后观察到的后续新run是`spacepilot_bc6148_rl_20261024_215949`；
需要显式`--run local/rl_training/spacepilot_bc6148_rl_20261024_215949`，时间和版本见[项目摘要](../current.md)。

## 采集、仲裁与奖励

periodic目标10Hz，latest观测与最新候选，不积压补发。缺少必需字段或非法数值不能构造有效输入；
**但缓存旧RGB仍可通过当前时序仅诊断路径**，camera mask为1不证明新鲜。断流门控待实施。
SpacePilot立即边沿的连续性／80–150ms间隔审核是另一层条件，不能代替相机新鲜度检查。

after-inference在推理完成后按最新人工输入仲裁，人工接管可能等待推理；immediate是另一配置。
停止、成功和断连优先处理；回合开始保留真实历史，回合外复位不录作训练动作。Marker当前关闭。
成功末条reward=1并terminated，其他正常步骤reward=0；普通结束／超时truncated并保留bootstrap。
来源和奖励是人工接管／标记语义，不等于独立自主评估。

## 更新与预算

真机SAC在[networks.py](../../src/omi_hil_rl/hil/networks.py)：共享编码器、双Critic与tanh高斯Actor，
当前v2 backup不含熵项，Actor有温度与人工动作BC约束；不要用仿真SB3描述这条路径。
主配置batch64、两流各100条门槛、1000次Critic预热；预热后仅触觉分支由Critic优化器更新，视觉和融合冻结。
探索噪声只加到policy归一化输出，标签保留最终已接受的命令。精确结构见[策略模块](policy.md)。

Learner每50次Critic更新发布；Actor每新增10个有效完成回合检查加载，回合中不换权重。
累计更新预算为预热加已登记online条数×配置比例；等待Start时Learner仍可训练到预算上限。
跨重启300回合上限按已开始回合计数；删除台账与现有回合ID取并集，避免清理坏数据返还次数。
详见[经验池](replay.md)和[删除台账接口](../interfaces/data-formats.md#删除回合台账)。

已有真实采集、BC拟合、在线更新和保存证据；策略质量、采集新鲜度与控制停止性能需分别验收。
操作：[异步RL](../../tutorials/async_rl.md) · [人工采集](../../tutorials/rl_episode_collection.md) · [网页](../../tutorials/training_monitor.md)。
历史：[在线RL归档](../archive/online-rl/README.md)。
