# SpacePilot BC6148在线RL：配置、新建与续跑

本页是当前选定配置的操作入口；机制见[在线RL模块](../docs/modules/online-rl.md)，最后一次现场记录见[项目摘要](../docs/current.md)。
运行必须显式传`--parameter`（别名`--settings`）；真机执行和策略分别通过`--execute --enable-policy`开启。

## 先选对任务目录

| 对象 | 路径及用途 |
| --- | --- |
| 原BC6148 | `local/rl_training/spacepilot_bc_20261017_213359_2000_4000`；新任务初始化来源 |
| 主JSON默认run | `local/rl_training/spacepilot_bc6148_rl_legacy_30s_300_20261017`；10月24日清理过的旧任务 |
| 最后一次观察到的新run | `local/rl_training/spacepilot_bc6148_rl_20261024_215949`；10月24日23:06记录从BC6148空池启动后正在训练 |

**省略`--run`会使用主JSON里的旧目录。** 新run不是旧30897权重的恢复；旧任务的45994条库存和剩余70回合不能套用到新run。
表中运行状态是10月24日快照，不证明现在仍在运行；操作前检查当前进程和实际目标目录，避免启动重复Actor或其他动作发布者。

## 已有任务续跑

从项目根目录执行。已有run保留完整checkpoint、经验索引、原始帧与会话配置；不要再次prepare。
以最后观察到的新任务为例：

```bash
cd /home/zhoutong/omi_folder/omi_proj

# 只读核对最终配置，不启动训练或机器人
bash scripts/run_async_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --run local/rl_training/spacepilot_bc6148_rl_20261024_215949 \
  --print-settings

# 既有进程正常退出后，恢复同一任务
bash scripts/run_async_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --run local/rl_training/spacepilot_bc6148_rl_20261024_215949 \
  --execute \
  --enable-policy
```

没有独立`--resume`开关。该入口恢复模型、优化器与磁盘经验，重建内存工作集；不是从BC重新开始。
旧任务如需恢复，显式换成旧run并核对其模型影响与数据状态，不能把清理经验当作回滚学习更新。
传感器和接收端使用已验证的现场配置，查看[设备入口](common_live_commands.md)与[接收端教程](robot_controller.md)。

## 从BC另建空池任务

只在需要新的独立实验时执行，目录必须尚不存在。主配置指定BC6148、weights-only，原BC数据不自动入池。

```bash
run_dir="local/rl_training/spacepilot_bc6148_rl_$(date +%Y%m%d_%H%M%S)"
bash scripts/prepare_bc_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --run "$run_dir"

# 初始化成功后，在同一终端使用同一个run
bash scripts/run_async_rl.sh \
  --parameter configs/spacepilot_bc6148_online_rl.json \
  --run "$run_dir" \
  --execute --enable-policy
```

空池需要新采人工接管数据，Demo与在线流各达到配置门槛后Learner才能更新；只有策略样本时等待人工数据是正常行为。
任意RL checkpoint另建空池尚无通用入口，不要用只替换actor.pt的方法冒充该操作。

## 当前显式设置与按键

完整参数以[主JSON](../configs/spacepilot_bc6148_online_rl.json)和`--print-settings`为准；CLI覆盖优先，初始化契约冲突会拒绝。
配置为30秒／回合、跨重启累计300个已开始回合、batch64、Demo/RL各100条门槛。
Critic预热1000次后触觉解冻，视觉与融合冻结；after-inference仲裁，每50次更新发布、每10个有效完成回合检查加载。
人工速度倍率为平移1.5／旋转0.3；探索只作用于策略。更多机制见[策略](../docs/modules/policy.md)和[人工输入](../docs/modules/teleoperation.md)。

| 按键 | 作用 |
| --- | --- |
| 数字1 | 开始回合 |
| Menu按住／松开 | 人工接管／交还策略；不是总停机 |
| ALT／Ctrl | 标记成功／普通结束 |
| ID26 | 回合外home |
| ID28／ID27 | 夹爪闭合／张开，无需按住Menu |
| ID8／ID2 | 标签跟随／保存映射保留，当前Marker关闭时不执行 |

按键来自本机已确认profile，换设备先按[SpacePilot教程](spacepilot_hil.md)核对实体ID。
人工夹爪启用不改变六维策略动作空间；review=auto，夹爪键不作为审核保留／丢弃按钮。
主JSON中`no_tag_follow=true`；关闭Marker不关闭RL视觉输入。ROS为domain13、SUBNET、非localhost-only。

正常Ctrl+C后等待保存和CLOSED再重启。累计300按已开始回合计算，包含异常回合；删除台账防止清理坏回合返还预算。
不能把一次进程的有效完成计数当作跨重启累计次数，规则见[数据接口](../docs/interfaces/data-formats.md#删除回合台账)。

## 观察训练与现场数据

```bash
# 另开终端，监控必须指向同一run；已有同端口服务时不要重复启动
bash scripts/view_training_monitor.sh \
  --run local/rl_training/spacepilot_bc6148_rl_20261024_215949 \
  --port 8768

# 独立只读现场看板
bash scripts/view_grid_observation_live_v2.sh --hz 10
```

网页地址`http://127.0.0.1:8768/`。监控只读，关闭它不停止训练；V2不启动传感器或动作执行。
当前时序仅诊断路径尚未全面拦截旧图，**看板正常或从BC空池启动都不等于训练数据新鲜度已验收**。
统一监控与门控待办见[设计](../docs/design/system-health-monitoring.md)。

当前任务配置与初始化快照保存在各run的`settings_prepare.json`、`settings_online.json`及会话文件中。
原始训练、清理、运行观察和本页旧版本保留于[在线RL归档](../docs/archive/online-rl/README.md)及[清理证据](../docs/evidence/external_camera_outage_20261024/README.md)。
