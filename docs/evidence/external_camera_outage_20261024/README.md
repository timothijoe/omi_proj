# 2026-10-24 外部相机断流与数据清理证据

记录对应[训练编年](../../agent/training/chronicles/2026-10-24-external-camera-outage-cleanup.md)。

- `outage_audit.json`：17:13审计快照、20个已入池回合ID与计数、像素抽查、恢复后窗口检查及原BC哈希。
- `cleanup_result.json`：20:54清理结果、删除范围、前后经验计数、隔离备份和未回滚权重声明。
- `buffer_validation.json`：临时缓存重建与两池batch64抽样；没有训练更新或机器人输出。
- `reference_validation.json`：剩余索引窗口哈希、源文件哈希、嵌套帧存在性及无已删除回合重新发现检查。
- `SHA256SUMS`：上述小型证据校验清单。

20个原始回合、30个派生片段及5681条经验已从活动任务删除，剩余45994条。
备份在 `local/archives/camera_outage_20261024_20_episodes/`，不属于训练扫描来源；原BC6148未改变。
RL30897没有回滚，仍应按可能受历史污染处理。剩余数据的结构检查不等于任务质量全部验收。
完整受影响样本ID清单及执行日志在本机diagnostics；本目录不包含图像、权重或完整数据库。
