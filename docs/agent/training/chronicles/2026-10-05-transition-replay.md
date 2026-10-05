# 2026-10-05：完整 transition 磁盘导入与在线分流 API

用户要求开发离线Demo/在线RL分流，并核查指定目录保存buffer、降低内存需求。
确认DiskHILReplayBuffer已有memmap/双流/预取/干净恢复；
原示范导入限仿真七维JSONL，真机policy＋RB未接池，EEF BC代理标签不能直接导入。

新增training.transition_replay，复用原磁盘池，提供create/append/inspect CLI、
完整JSONL逐行导入及Python append。显式观测/动作/奖励契约，
成功离线human只属Demo，在线policy属RL，在线human属两流且失败也保留。
episode/step及两观测时间随ring落盘，覆盖/重开保留对应关系。

相关26项测试通过，覆盖CLI真实创建/追加/检查、图像memmap/uint8、
双流抽样、失败接管、错误/代理/缺失数据拒绝、像素溢出/小数、ring及重开契约，
另复验旧示范导入、最终动作入池、磁盘后端。[操作教程](../../../../tutorials/transition_replay.md)。

不连接设备、不发动作、不训练模型。真机ROS transition配对、reward/episode、
命令确认、动作归一化和learner仍待实现；没有自动转换BC或补造奖励。
OS页面缓存占内存，无严格RAM上限、图像/历史去重、多进程同时打开、
冷盘长时验收、异常退出自动恢复；文件导入无事务/去重。
