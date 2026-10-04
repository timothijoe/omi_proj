# 2026-10-03：历史实验数据外置归档（复制完成，迁移暂停）

用户指定将 `local/tactile/`、`local/bc/`、`local/eef_bc/` 移至
`/media/zhoutong/zt-think-d1/legion_data/legion_omi_proj/local/oct_02/`，保留程序与运行依赖。

目标为已挂载的exFAT移动硬盘，初始目标目录为空，可用约901 GiB。
使用 `rsync -rt` 复制首批228个普通文件、58个目录，内容共14,352,271,055字节。
源中未发现软链接；exFAT不保留Unix权限/所有者语义，复制以内容和目录结构为准。
执行文件系统同步后，通过 `rsync -rcn --itemize-changes --stats` 内容校验：
已复制文件未报告内容差异，但源出现新建的 `eef_bc/oct3_formal_v3_run1/` 三个文件。
随后检查又发现训练曲线及分包验证结果继续生成，表明并行任务仍在使用该目录。

因此未移除任何源文件、未释放本机空间、未创建软链接，未停止其他进程。
移动盘只有首批副本，不是完整的最新快照；需要用户确认相关写入结束后，
再增量复制、校验和完成源目录移除。现有开发改动保留，不提交、不push。

当前资源位置和后续恢复规则见[本地资源接口](../../interfaces/local-resources.md)，
操作者说明见[迁移清单](../../../../tutorials/machine_transfer_checklist.md#历史实验数据的归档位置)。
