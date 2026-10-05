# 日期 bag → 含双指六维力/力矩的 BC 训练

2026-10-05 已将 `local/bags/demo_20261005_*` 四个真实包转换为正式的
**记录指令监督 BC** 数据，并完成首轮1000步 CUDA 训练。原始 bag 保持不变。
这是离线模仿训练，不自动连接机器人或启动在线 RL。

## 本次产物

| 原始 session | 用途 | 有效样本 | 非零动作 | 连续片段数 |
| --- | --- | ---: | ---: | ---: |
| demo_20261005_204815 | 训练 | 146 | 114 | 2 |
| demo_20261005_204853 | 训练 | 195 | 120 | 1 |
| demo_20261005_204949 | 训练 | 503 | 319 | 2 |
| demo_20261005_205111 | 验证 | 161 | 95 | 3 |

总计1005条，训练844条，验证161条。按整包划分，重叠历史帧不会横跨训练/验证集。
片段间缺口保留为元数据，不把稀疏样本拼成连续 RL transition。

- 数据：`local/passive_bc_20261005_wrench/`
- 数据划分与样本哈希：该目录 `plan.json`
- 来源、过滤原因、每包统计：该目录 `report.json` 和 `episodes/*/dataset.json`
- 本次训练：`local/passive_bc_20261005_wrench_train_v1/`
- 日志：`local/passive_bc_20261005_wrench_train_v1.log`
- 运行进度：训练目录的 `progress.json`、`history.json`
- 验证集最优模型：`actor.pt`；训练结束另写 `last.pt` 和 `report.json`

## 数据与模型含义

动作来自实际录到的 `/omi/controller_test/decision`。按照用户已确认的
`sdk-x-forward-z-left` 设置，将 SDK XYZ 毫米/ABC 角度逆转换为策略坐标下的
米/旋转向量弧度，并逐条检查正向转换能够还原原 wire 指令。
归一化尺度为每轴0.0005米、0.5度对应的弧度，来自10Hz、scale0.5的发布配置；
超过已确认普通手柄速度上限的命令会剔除，不静默裁剪成示范。

观测沿用10Hz固定时间网格和strict源header检查，要求当前及过去九帧完整。
每个观测对应随后 `[t,t+100ms)` 中恰好一条实际指令，输入只使用截至t已收到的数据。
BC不需要未来EEF作为标签，所以取消了预览专用的“下一EEF必须在指令之后收到”条件；
第三包因此由335条审阅样本增加到503条BC样本，未放宽传感器时效检查。

网络使用双相机、双指deformation/shear/depth、EEF和十帧历史；关节与夹爪输入关闭。
新增 `wrench[10,2,6]` 与 `wrench_mask[10,2]`，顺序A/B各Fx、Fy、Fz、Tx、Ty、Tz。
每个历史槽取不晚于该槽的最近wrench消息，最大接收年龄250ms；本次保留样本的20个
双指历史槽均有效。原header、接收时刻、frame_id同时保留作审计。

力/力矩保留原始SDK数值，不宣称已校准N/Nm，不按机器人坐标擅自换轴。
只用训练集有效值计算每根手指各分量的均值/标准差；归一化后的120个历史数值及20个
mask进入MLP分支，再与原有视觉/三场触觉/EEF特征融合。梯度测试确认该分支参与预测和学习；
视觉ResNet-10骨干使用现有官方转换权重并保持冻结。

数据使用独立schema `omi-passive-command-bc-wrench-v1`，动作语义明确为
`recorded_command_not_execution_confirmed`。原包缺少逐指令receipt、成功标记及自动返回模式，
因此不是确认物理执行的RL经验，也不声称整包都是成功示范。当前发布配置中的
`home_usage=not yet confirmed`保留在产物中；成功奖励不参与BC。
后续若确认有自动返回，应提供时间段重新排除并生成新版本数据。

本模型增加了wrench输入并使用新的动作尺度/数据契约。
现已提供[专用实时入口与RB接管命令](wrench_policy_gamepad.md)：
`scripts/run_wrench_policy_gamepad.sh`，默认仅预览，显式`--execute`才发真机命令。
旧模型默认入口及HIL在线训练ROS路径不自动兼容这个契约，不能只替换checkpoint路径。

## 复现转换

使用新输出目录，避免覆盖本次数据：

```bash
source scripts/env_ros.sh
source local/ros2/robot_controller_ws/install/local_setup.bash
python -m omi_hil_rl.training.passive_bc \
  --sessions local/bags/demo_20261005_204815 local/bags/demo_20261005_204853 \
             local/bags/demo_20261005_204949 local/bags/demo_20261005_205111 \
  --provenance local/four-demo-audit-20261005/publisher_provenance.json \
  --output local/passive_bc_20261005_wrench_new \
  --validation-session demo_20261005_205111
```

可加 `--exclusions FILE.json`，内容为 `{session名称: [[起始秒,结束秒], ...]}`，
以该包第一个所用传感器接收时刻为零点，按命令接收时间排除区间。

## 训练与查看进度

本次参数为CUDA、1000步、batch32、学习率0.0003、seed7、每100步完整评估。
已有本次训练运行时不要重复启动同一目录；复现命令如下：

```bash
PYTHONPATH=src:ros2/omi_sensors:/usr/lib/python3/dist-packages \
CUBLAS_WORKSPACE_CONFIG=:4096:8 \
local/cuda-env/bin/python -u -m omi_hil_rl.training.demo_bc train \
  --plan local/passive_bc_20261005_wrench/plan.json \
  --output local/passive_bc_20261005_wrench_train_new \
  --pretrained local/pretrained/serl_resnet10/backbone.pt \
  --steps 1000 --batch-size 32 --learning-rate 0.0003 \
  --evaluate-every 100 --seed 7 --device cuda --threads 4
```

```bash
tail -f local/passive_bc_20261005_wrench_train_v1.log
```

每10步更新进度，每100步记录全训练/验证集误差并选择验证MSE最小的checkpoint。
还报告非零动作误差；结束时对比零动作/训练均值基线，并检查checkpoint重新加载一致性。
离线动作误差不代表USB插入成功率。

## 排除第三包的对照训练

用户观察到现场模型持续负X，要求去掉第三个示范包重训。新plan为
`local/passive_bc_20261005_wrench/no_third_plan.json`，只排除训练包
`demo_20261005_204949`，原始bag、样本、原plan和旧检查点均保留。
训练仅用前两包146+195=341条；验证仍用第四包161条，不改变验证划分。
训练集中X正/零/负分别188/136/17条，因此这不是“所有负X删除”实验。
双侧wrench仍参与训练。参数保持1000步、batch32、lr0.0003、seed7、每100步评估；
从同一预训练视觉骨干重新训练，不从旧BC模型续训，归一化统计只用新的训练划分重算。
训练输出`local/passive_bc_20261005_wrench_no_third_train_v1/`，日志为同名前缀`.log`。
最终指标以该目录`report.json`为准；真机脚本仍默认旧模型，不自动切换或执行。
删除整包同时改变正向样本量及场景分布，不能仅凭结果变化就认定负X示范是根因。

本轮已完成1000步并正常退出，检查点复载一致、冻结骨干未变化均通过。
相同验证包：旧模型最佳归一化MSE=0.057797；新实验第100步=0.116023（已评估更新后最佳），
第1000步=0.158404。新实验训练MSE降至0.000271，验证表现反而恶化。
特别注意：选择规则包含第0步，本轮`actor.pt`选中的是**第0步、未做BC更新的初始模型**，
验证MSE=0.109406，不应误称为训练后改善模型或部署替换。
`last.pt`保留1000步权重与优化器状态，但不是实时入口支持的actor发布格式。
本次结果不支持通过删除第三包改善泛化，不代表已经解决现场负X问题；未启动真机或替换默认检查点。
