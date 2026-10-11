# 2026-10-11：问题采集数据归档，原路径恢复BC空池会话

最新操作见文末“第二次清空并改为45秒”；同一活动目录当前实际时限已为45秒，名称中的30s仅为历史命名。

用户报告 `local/rl_training/bc12045_newdata_30s_20261011_01/` 的采集数据有问题，
要求清空此前采集数据、保留模仿学习checkpoint。

操作前确认Actor/Learner均为CLOSED、无error，两个owner锁可获取，replay为clean。
在持有旧会话owner锁期间，先于临时目录准备并验证新的30秒weights-only会话，再交换目录。
旧会话完整归档，不仅隔离原始数据和索引，也隔离已在问题数据上训练的RL1714模型及优化器状态。
未启动机器人或训练进程。

## 归档与校验

- 归档：`local/archives/problematic_data/bc12045_newdata_30s_20261011_01_20261011_183427/`。
- 3个已保存回合，原索引714条transition：375人工、339策略，固定seed=0。
- 2985个归档文件，166,657,555逻辑字节；逐文件SHA-256一致，操作进程退出后再次核验通过。
- 证据：`local/diagnostics/data_reset_20261011/20261011_183427/report.json` 与 `archive_hashes.json`。
- 原始BC来源：`local/bc_episodes/demo_new_20261007_213643_eval_01/actor.pt`，版本12045。
- 原BC SHA-256前后相同：`47838ba160722c3096e98c5e39cfc3a71b2ea1d786470f93662b4c6dc0eb053f`。

## 重建后的状态

活动路径仍为 `local/rl_training/bc12045_newdata_30s_20261011_01/`，所以用户原启动命令继续有效。
Demo=0、RL=0、固定seed=0、回合=0、Learner更新=0；无外部录制来源，原BC参数逐张量一致。
时限仍30秒，缓存16/20 GiB，预热1000步；探索和换权重间隔由原启动命令继续显式传入。
原路径的 `data_reset.json` 记录归档定位及原因。问题数据归档不在新会话自动导入范围内。

刷新 http://127.0.0.1:8771/ 可看到新的空池统计；API已核对所有回合计数及两池初始登记数均为0。
后续需要重新采集有效人工接管数据满足 `--min-demo 100`，旧数据不会用于凑齐门槛。
启动时版本0表示新RL会话的更新计数，其Actor参数仍来自BC12045。

完整启动命令沿用[30秒会话记录](2026-10-11-30s-buffer-dashboard.md)。归档仅用于追查或恢复，
不要作为 `--recorded-source` 传回当前训练，也不要把归档中的RL权重拷回活动目录。

## 第二次清空并改为45秒（18:43）

用户再次要求清空，并将timeout从30改为45秒。检查时Actor/Learner均正常CLOSED、锁可获取。
将新增4个回合、792条transition（481人工、311策略）及RL1792完整归档至：
`local/archives/problematic_data/bc12045_newdata_30s_20261011_01_20261011_184301/`。
4521个文件、204,824,354逻辑字节，逐文件SHA-256一致，操作退出后再次核验通过。
本次证据在 `local/diagnostics/data_reset_20261011/20261011_184301/`。

原路径重建为空池，仍完整继承原BC12045，原BC文件哈希未变，RL更新计数0。
新config、Actor/Learner checkpoint、session及replay契约全部统一为45秒，
没有只改config而留下不一致的模型契约。Demo/RL/固定seed/回合均为0，未启动机器人。
活动文件夹名称保留30s，以便原启动命令继续有效；真实时限以config中的45秒为准。
8771监控API已核对空池、0回合及45秒时限，刷新页面即可查看。
