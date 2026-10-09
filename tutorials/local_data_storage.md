# 本机 local 与外接盘数据的使用

2026-10-09 已将选定冷数据迁到
`/media/zhoutong/zt-think-d1/omi_proj_data/local/`。
完成状态见 `local/storage_migrations/20261009_202357/manifest.json`。
目录选择与本机保留清单见[存储契约](../docs/agent/interfaces/local-storage.md)。

## 读取迁出的数据

挂载移动盘后，原命令中的 `local/...` 仍可使用：项目中的软链接指向外盘相同层级。
两个 local 都不是对方的整体副本。当前 RL live、新 BC/seed、新示范和运行环境留在本机。

从项目根目录进行只读检查：

```bash
findmnt -T /media/zhoutong/zt-think-d1
readlink -f local/eef_bc
readlink -f local/rl_training/bc_demo_new_20261007_213643_rl_probe_01
du -sh local
df -hT . /media/zhoutong/zt-think-d1
```

`du -sh local` 默认不跟随目录软链接，反映本机保留量；`du -shL local` 会跟随链接，
用于查看整个逻辑资源树，盘挂载时才有意义。外盘路径应由 `findmnt` 确认是挂载盘，
不能只凭目录存在判断已挂载。

盘未挂载时，读取已迁出数据会失败。请挂载到原路径后重试；不要删除失效链接、
在挂载点创建替代数据或重新生成同名空目录。新文件写进已迁出目录也会落在外盘。

## 继续当前 RL 与新建采集

当前 `local/rl_training/bc_demo_new_20261007_213643_rl_live_01` 及其新示范/seed 保留本机，
使用[异步 RL 教程](async_rl.md)中指向该目录的命令。
新建会话仍选择本机 `local/rl_training`、`local/rl_episodes`、`local/bc_episodes`
或 `local/wrench_live` 下的新名字。不要对本次已迁出的旧 RL 会话直接续训。

## RViz 回放与同日系统清理

三份代表原包留在 `representative_rosbag/october/`，原生场、腕部、grid 与旧 record010
显示缓存则经项目 `local` 中的软链接读取外盘。使用现有录包回放脚本仍需挂载移动盘；
现场实时看板不使用这些录包缓存。具体对应关系见[RViz 操作页](rviz_representative_bags.md#原包显示缓存和训练示范包)。

同日还完成 pip/npm 下载缓存清理及定制音频内核的完整备份、生成文件清理。
备份位于用户指定的移动盘“legion笔记本历史性质的备份/历史备份”下，
目录、保留范围和恢复说明见[主机清理记录](../docs/agent/interfaces/local-storage.md#同日主机空间清理与内核备份)。

## 恢复旧会话

1. 关闭使用该目录的训练、查看器或采集进程，并确认 SSD 空间足够。容量按表观大小预算；
   例如旧双池 replay 的稀疏数组在外盘会展开。
2. 将外盘完整会话复制到原工作路径旁的新临时目录。支持稀疏文件的复制工具可在 ext4
   上重新节约零区域，但仍以内容哈希验证结果。
3. 按迁移证据 `files.sha256.jsonl` 核对相对路径、文件数量、大小与 SHA-256。
   单独恢复某个目录时，只选其相对路径前缀的记录。
4. 校验通过后，只移除原工作路径的软链接，将临时目录改为原名。保留外盘完整副本，
   确认所有 `dataset.json` 来源路径可读、replay 干净、检查点一致后，再按原教程恢复。

迁移证据在本机 `local/storage_migrations/20261009_202357/`，外盘有独立副本
`/media/zhoutong/zt-think-d1/omi_proj_data/migrations/20261009_202357/`。
这里包含计划、每目录状态、逐文件哈希、执行脚本和统计；原始实验 JSON、NPZ、权重不改写。
完整跨机器恢复还需要 Git 代码、当前本机资源及对应运行环境，外置冷数据不是整项目备份。
