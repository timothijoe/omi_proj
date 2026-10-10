# 2026-10-10：旧格式与 SDK 错误回合迁移

用户要求把当前数据中的旧格式回合及SDK错误回合移到
`/home/zhoutong/Downloads/oct10/old_version_data/`，工作目录暂时保留有意义的数据。
本次按已讨论的两个会话筛选，不扩展到其他历史模型、示范或归档目录。

## 已执行

| 来源（相对项目local） | 筛选条件 | 回合 | 动作记录 | 文件数 | 字节 |
| --- | --- | ---: | ---: | ---: | ---: |
| `bc_episodes/demo_new_20261007_213643_eval_01/periodic_episodes` | 当前BC会话旧格式，无单帧存储版本标记 | 12 | 2210 | 2270 | 1,755,454,463 |
| `rl_training/bc12045_obs_after_inference_20261009_01/periodic_episodes` | 完整audit明确 `receiver fault: sdk_rejected` | 4 | 301 | 639 | 534,995,871 |

归档目标保留相对于 `local/` 的上述目录层级。共16回合、2909个文件、2,290,450,334字节，
逐文件迁移前后SHA-256和文件清单一致；所有源回合路径已移除，不留软链接。
源/目标在同一文件系统，使用目录重命名；只是整理位置，没有减少整块磁盘的总占用。

迁移时未发现BC/async RL/Learner运行进程，并持有两个会话的Actor与Learner目录锁。
所有迁出回合均 `training_ready=false`、无训练片段；没有移动训练片段所依赖的帧库。
两个会话的模型、配置、recipe、dataset及保留回合audit在前后哈希核对中一致。

完整来源、目标、每个文件大小/哈希以及会话元数据快照：
`/home/zhoutong/Downloads/oct10/old_version_data/manifest.json`。
归档目录的 `README.md` 提供范围和恢复说明。

## 保留与解释

当前BC工作目录 `local/bc_episodes/demo_new_20261007_213643_eval_01/periodic_episodes/`
现在仅保留本批19个单帧格式完整回合、3617条动作：8个按键成功、10个正常超时、1个人工结束。
正常超时和人工接管数据仍可能有训练价值，未因没有成功标签而迁出。

此前RL会话中的成功回合 `f0c81d936b094349a71f0250bbcffbf1` 与其既有训练片段留在原处。
无完整audit的暂存回合 `0b02f61125354b3c9f555211485016f7` 也保留，未归类为SDK错误。
该会话状态文件还记录过 `EpisodeSpool.__init__()` 不接受 `frame_writer` 的writer异常；
本次只做归档，没有修复、续跑或把这个异常当作SDK拒绝处理。
本次“旧格式”筛选针对当前BC评估目录，不对其他会话所有旧格式数据做全局清理。

原始BC与RL权重、经验池、人工示范源均不变。没有训练、重启设备或修改成功/失败标签。
历史进展页中的31回合总数是迁移前快照，迁移后当前BC目录为19回合；查旧路径需用归档manifest映射。
