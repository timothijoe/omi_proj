# SpacePilot 在线RL停止后核验

2026-10-18按用户要求只读核验；实际停止于2026-10-17 23:42:42（北京时间）。本包补充此前23:29运行快照，不覆盖历史证据。代码基线为`63e6fad`。

- [snapshot.json](snapshot.json)：停止状态、权重元信息、67份回合审计、经验目录统计、校验结果及源文件SHA256。
- [SHA256SUMS](SHA256SUMS)：本包文件校验清单。
- [停止编年与续跑说明](../../agent/training/chronicles/2026-10-18-spacepilot-rl-stopped.md)。

Actor与Learner均CLOSED，error=null、learner_forced_kill=false，两份权重updates=4628，Actor张量完全相同且模型张量有限，优化器状态存在。停止前操控实际加载4150；下次启动读取磁盘最新4628，非回退4150。

67原始回合：43成功标记、17超时、6普通结束、1输入断连；66可训练，13360条已全部登记。其中人工5259、策略8101，初始seed0；43条正奖励对应43个成功回合。回合允许人工接管，不能将成功标记解释为自主成功率，也不能把最后一步来自策略解释为整回合无接管。

数据库quick_check=ok，全部records引用的当前/下一步文件存在，sources中审计文件哈希一致，未发现只有staging而无audit的原始回合。replay clean=true。累计已开始67回合，上限300还剩233。

核验不调用ROS，不推理、不更新模型、不重建生产缓存；没有逐个解码或哈希所有嵌套图像帧，也没有做完整恢复试跑，因此这是保存状态与索引完整性检查，不是所有样本内容和真机效果验收。旧monitor中的传感器LIVE、loader_busy等字段是停止前残留状态，不能据此断言进程仍活着；记录的两个PID均已不存在。

原始数据与权重仍位于`local/rl_training/spacepilot_bc6148_rl_legacy_30s_300_20261017/`，本证据包不是完整模型/数据备份。

```bash
cd /home/zhoutong/omi_folder/omi_proj/docs/evidence/spacepilot_rl_stopped_20261018
sha256sum -c SHA256SUMS
```
