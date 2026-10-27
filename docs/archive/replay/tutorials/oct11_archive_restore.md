> 历史资料：原路径 `tutorials/oct11_archive_restore.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../modules/replay.md)；本页保留原过程与证据。

# Oct 11在线RL归档、恢复与buffer重建

本页对应2026-10-11停止的45秒、batch64在线会话。
原目录为 `local/rl_training/bc12045_newdata_30s_20261011_01/`；名称中的30s不代表实际时限。
停止时最终Actor/Learner checkpoint均为 **16677**，Actor实际执行的最后版本为16150。
有效数据目录共53513条，其中9754条人工数据，固定历史seed=0。
最后一个回合另有449条有效数据已保存但停止前尚未登记；原始文件已完整归档，正常Learner续跑会补导入。
外盘 `RESTORE_VALIDATION.md` 和 `validation/` 保存实际恢复/模型/buffer验证结果。
这些是停止时的数据规模；恢复后的驻留内存数量由缓存预算决定，不等于全量目录数量。

归档位置：

```text
/media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data
```

外盘是exFAT。本次使用未压缩tar封装已经压缩的NPZ，避免大量小文件各自消耗大分配单元。
本机原会话保留，不在归档成功前删除唯一来源；本接口没有自动清理本机源目录。
归档包含当前会话的全部原始记录（含异常/中断审计）、索引、配置、日志与权重；
此前两次被用户否定的数据已经另行归档，不混入这份当前会话。

## 归档包含什么

| 文件 | 用途 |
| --- | --- |
| `run.tar` | 完整会话，含frames、窗口引用、动作、回执、SQLite索引和最终模型 |
| `run_files.sha256.jsonl` | 会话逐文件大小及SHA-256 |
| `checkpoints/actor.pt` | 最终发布的Actor16677，方便单独取用 |
| `checkpoints/learner.pt` | 完整续训状态：Actor/Critic/target、优化器、温度、随机状态、更新计数 |
| `initial_bc/actor.pt`、config/recipe | 原始BC12045，用于重新从BC建立空池任务 |
| `source.tar`、`source_files.sha256.jsonl` | 归档时实际代码/文档快照，包含未提交的新恢复入口 |
| `manifest.json` | 格式、来源、代码commit/工作区状态、目录计数、各归档与附属文件校验值 |
| `environment.json` | 打包环境Python及主要依赖版本；未打包整个venv或厂商SDK |
| `archive_tool.py` | 标准库恢复入口；没有项目环境也能校验和解包 |
| `README.md` | 本教程的归档副本 |

若存在 `ARCHIVE_INCOMPLETE`，表示打包或校验没有完成，不能用于恢复。
代码快照是当时实际文件，不宣称完全等于HEAD；具体差异状态在manifest中。
模型文件是归档时16677快照，不包含每50步发布时的所有历史版本。

## 1. 校验外盘归档

标准库即可执行，校验会顺序读取全部归档内容，需要一些时间：

```bash
python3 /media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data/archive_tool.py verify \
  --archive /media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data
```

在现有项目中也可用 `bash scripts/training_archive.sh verify --archive ...`。
校验检查tar整体SHA、每个文件SHA/大小/数量及单独模型等附属文件，不启动设备、不训练。

## 2. 恢复到本机新的工作目录

目标目录必须不存在；不要覆盖正在使用的任务。外盘归档保持不变。
工作目录应位于本机ext4等POSIX文件系统，接口拒绝直接恢复到exFAT/NTFS工作目录。

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/training_archive.sh restore \
  --archive /media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data \
  --dest local/rl_training/oct11_restored_01
```

解包时逐文件核验，全部成功后才发布目标目录。原始文件内容不改写。
这个会话的SQLite来源指针及帧引用均相对会话目录，dataset没有旧Demo、sources也为空，
因此改成新目录仍可读取；初始化来源和旧归档路径只是provenance，不是这批训练数据的运行依赖。
本归档接口特意拒绝存在外部数据来源或旧seed依赖的会话，避免做出不完整的可迁移包。

没有项目目录时，可先恢复代码快照到一个全新目录：

```bash
python3 /media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data/archive_tool.py restore-code \
  --archive /media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data \
  --dest /home/zhoutong/omi_folder/omi_proj_oct11_source
```

解包代码不等于安装环境。另一台机器仍需按 `environment.json`、`pyproject.toml` 和项目环境教程
安装匹配的Python、Torch/CUDA、NumPy、Gymnasium、stable-baselines3；网页还需要Pillow。
脚本入口使用 `local/cuda-env/bin/python`，环境需在恢复后的项目内准备。
真实机器人还依赖ROS、消息定义、厂商SDK、接收端和传感器，未将这些依赖冒充为归档内已安装环境。

## 3. 复现buffer：先只读试装，不训练

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/training_archive.sh probe-buffer \
  --run local/rl_training/oct11_restored_01 \
  --cache-target-gib 1 --cache-limit-gib 2 \
  --batch-size 64 \
  --report local/diagnostics/oct11_restored_buffer_probe.json
```

此处1/2 GiB仅用于快速复现验证，不覆盖正式会话的16/20 GiB配置。
接口复制一份临时SQLite，临时重定位指针，调用生产CachedDualReplay读取原始帧、重建十帧窗口、
分别进行Demo/RL混合抽样和纯Demo抽样，并检查checkpoint契约与版本一致性。
原恢复目录的模型、SQLite及manifest前后哈希一致；临时缓存退出即释放，训练更新数为0。
报告已存在时应换新报告名。测试要求任务已停止且两池都有数据。

正式Learner重启时也会自动根据 `replay/catalog.sqlite3` 重新填充内存，
无需先把全部数据转换成展开NPY，更无需把53513条全部塞入RAM。
RAM旧数组本身没有持久化：恢复的是同一数据/标签和可重建窗口，不保证相同的驻留成员、抽样顺序或逐位相同的学习轨迹。
全量数据在硬盘；Demo/RL人工交集共享，16 GiB是两池合计驻留目标、20 GiB是受管管线预算。

## 4. 只运行Learner，验证恢复续训

以下会修改**恢复副本**的权重和日志，外盘归档不变；无机器人输出：

```bash
local/cuda-env/bin/python -m omi_hil_rl.hil.learner \
  --run local/rl_training/oct11_restored_01 \
  --config local/rl_training/oct11_restored_01/config.json \
  --device cuda --batch-size 64 \
  --min-online 100 --min-demo 100 \
  --publish-every 50 --updates 20 \
  --max-updates-per-transition 1
```

`--updates 20`是本次追加20次，正常情况下从16677继续到16697，不是重置训练到20。
不要运行prepare_bc_rl覆盖恢复副本；续训直接读取learner.pt，包括原gamma0.98及冻结编码器设置。

## 5. 恢复在线采集和监控

仅在现场接收端/传感器就绪且没有其他动作发送端时，由操作者启动：

```bash
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
bash scripts/run_async_rl.sh \
  --run local/rl_training/oct11_restored_01 \
  --actor-device cuda --learner-device cuda \
  --batch-size 64 --publish-every 50 --reload-every-episodes 10 \
  --min-online 100 --min-demo 100 --max-updates-per-transition 1 \
  --arbitration-mode after-inference \
  --exploration-noise-std 0.05 --exploration-noise-clip 0.15 \
  --no-gripper --execute --enable-policy
```

时限45秒已在config和checkpoint契约中，夹爪沿用闭合假设；探索参数每次启动显式传入。
正常Ctrl+C保存退出后可用相同命令续跑。

监控另开终端，指向**恢复目录**，无需在浏览器里选择文件夹：

```bash
bash scripts/view_training_monitor.sh --run local/rl_training/oct11_restored_01 --port 8773
```

打开 http://127.0.0.1:8773/ 。未启动训练时显示归档中的关闭状态，是正常现象。
不要将 `--run` 指向run.tar或外盘bundle根目录；它必须指向解包后的完整会话目录。

## 重新从原BC采新数据

归档中的 `initial_bc/` 可作为BC来源目录，使用 `--weights-only --episode-seconds 45` 创建另一个新任务。
这会丢弃本任务的RL学习进度并从空池开始，不是续训16677。
只取 `checkpoints/actor.pt` 不能恢复优化器或buffer；完整续训请恢复run.tar。

## 今后归档其他同类会话

停止Actor/Learner并等待CLOSED后执行，输出目录须为空：

```bash
bash scripts/training_archive.sh pack \
  --run local/rl_training/bc12045_newdata_30s_20261011_01 \
  --output /media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data \
  --initial-bc local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --code-root . --tutorial tutorials/oct11_archive_restore.md
```

本次归档已存在后不要重复覆盖，应换新的归档目录。过程持有会话锁、完整校验后才移除未完成标记；
不会自动删除原会话，也不会启动训练或机器人。
