# 2026-10-03：完成tactile和bc迁移，保留eef_bc

接[首次复制与暂停记录](2026-10-03-experiment-data-archive.md)，用户明确要求保留未完成
迁移的 `local/eef_bc/`，移除另外两个已复制目录的本地副本。

再次确认移动硬盘已挂载、源和目标目录存在；打开文件检查未发现两个源目录被占用
（lsof提示无关的 `/tmp/fuse` 无法扫描）。`rsync -rcn --itemize-changes --stats`
校验153个普通文件、31个目录，文件总内容8,007,932,419字节，无缺失、无内容差异。
随后用 `rsync -rc --remove-source-files` 再次校验并移除成功归档的源文件，
只清理这两个源目录下的空目录，不操作 `local/eef_bc/`。

归档保留在 `/media/zhoutong/zt-think-d1/legion_data/legion_omi_proj/local/oct_02/`
的 `tactile/` 和 `bc/`。本地源目录不留软链接，释放约7.46 GiB；可从移动盘恢复。
移动盘 `eef_bc/` 仍是旧副本，本地 `local/eef_bc/` 才是继续使用的数据。
程序、SDK、模型、原始bag与其他开发修改不变；没有停止进程，没有commit或push。

当前状态见[资源接口](../../interfaces/local-resources.md)，操作说明见
[迁移清单](../../../../tutorials/machine_transfer_checklist.md#历史实验数据的归档位置)。
