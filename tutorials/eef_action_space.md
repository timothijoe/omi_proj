# bag_004：末端动作空间、BC与影子推理

`local/eef_bc/` 按用户要求继续保留本地使用；移动盘只有首批副本，不是完整最新备份。
位置与后续路径使用方式见[迁移清单](machine_transfer_checklist.md#历史实验数据的归档位置)。
本教程的本地末端实验路径不受此次迁移影响；本次仅移除了已校验归档的 `local/tactile/` 和 `local/bc/`。

新版可选腕部的配置、维度和复现实例见下方[第6节](#6-开启或关闭腕部相机v2)。前面命令继续对应原单相机v1。

从项目根目录执行。第一版为左臂六维基座系增量，单位米和旋转向量弧度，10 Hz；
每步相对当前录制EEF，不包含夹爪。数据标签来自未来录制位姿变化，未确认是控制动作。
所有命令用于离线或localhost回放，不连接机器人。

## 1. 准备环境与类型化消息

沿用[BC环境准备](bag_bc_shadow.md#1-准备)：Jazzy、匹配Marvin消息overlay、MCAP/zstd、
项目Python3.12与BC依赖。本轮在Ubuntu24.04/Jazzy验证；Humble尚未验证。
不需要机器人URDF、触觉SDK或腕部图像；不会改变已有RViz窗口。

首次构建新消息（需要colcon、ament_cmake、rosidl_default_generators及标准消息开发包）：

```bash
source /opt/ros/jazzy/setup.bash
colcon --log-base local/action_ros/log build \
  --base-paths ros2/omi_action_msgs \
  --build-base local/action_ros/build \
  --install-base local/action_ros/install \
  --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
bash scripts/eef_bc.sh --help
```

脚本自动读取 `local/robot_state/viewer.env` 的Marvin路径，并source新消息overlay。
构建物放在Git忽略的local下，换机重新构建。
默认localhost domain92；可以用 `OMI_EEF_DOMAIN_ID` 选择另一个空闲非零隔离域。

## 2. 导出代理标签数据

```bash
bash scripts/eef_bc.sh export /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip \
  local/eef_bc/bag004_dataset --accept-future-state-proxy
```

输入路径按机器修改；该参数明确接受“未来状态变化代理标签”实验含义。
输出目录必须不存在。准备约3GB空闲空间供解压与11路观测MCAP使用。
输出samples.npz、manifest.json、references.json和observations/；不回放原始控制指令。
当前示例得到69条标签样本；通过manifest查看缺失和过期拒绝原因，不以放宽阈值补齐。

state为26维；action为6维。名义未来窗口100ms、容差20ms，实际时间跨度另存。
外部相机固定ROI和触觉16×24均值处理沿用现有配置。
腕部不进入本次输入；其采集问题仍按原约定暂缓。

## 3. 训练

```bash
bash scripts/eef_bc.sh train --train local/eef_bc/bag004_dataset \
  --output local/eef_bc/policy_bag004_smoke --overfit-smoke --steps 500
```

生成policy.pt、report.json、train_predictions.npz。模型确实反向更新，但这个模式只检查
单段拟合，没有验证集，不提供任务成功率。检查报告中的平移/旋转分量RMSE及零增量基线。
有独立episode后用 `--validation DATASET...` 替换 `--overfit-smoke`。
旧七关节policy.pt与新版互不兼容，不要混用。

## 4. 两轮ROS影子验证

```bash
bash scripts/eef_bc.sh shadow --dataset local/eef_bc/bag004_dataset \
  --checkpoint local/eef_bc/policy_bag004_smoke/policy.pt \
  --output local/eef_bc/shadow_bag004_verified --loops 2
```

本机示例预期140次（每轮70），typed_proposals_received也是140，errors为空，
no_control_topics为true。每轮故意暂停1秒检查过期，循环开始清空历史；运行结束自动退出，
Ctrl+C可取消并清理本工具启动的子进程。

输出 `/omi/eef_shadow/policy_proposal`，类型 `omi_action_msgs/msg/EefActionProposal`。
它是候选动作，包含参考时刻、frame、米/弧度、POLICY来源、锚点及候选目标位姿、shadow_only。
status为JSON诊断；预测日志与报告保存在输出目录。不向任何控制topic转发候选。
没有人工接管、IK、安全执行或真实在线采样入口，不能只换domain就上真机。

## 5. 查看六维动作对比图

以下使用已安装NumPy/Matplotlib的解释器；本机为系统Python：

```bash
/usr/bin/python3 scripts/plot_eef_actions.py \
  local/eef_bc/bag004_dataset local/eef_bc/policy_bag004_smoke \
  local/eef_bc/bag004_action_comparison.png
```

蓝线为未来录制位姿变化，橙线为同段BC预测；平移显示mm，旋转显示旋转向量分量角度。
图中每一点都相对自己的录制锚点，不是预测驱动的连续轨迹或闭环评估。
图像也拒绝覆盖；复跑时选择新文件名。

常见错误：缺少omi_action_msgs时先完成第1步；数据/模型契约不符时用匹配版本重新导出和训练；
EEF frame或时间校验失败时核实源数据；越界候选被拒绝时检查模型和标签，不放大阈值假装验收。
完整契约与限制见[当前说明](../docs/agent/training/evolution/eef-action-space.md)。

## 6. 开启或关闭腕部相机（v2）

在第2节导出时增加`--wrist-camera`。支持：

- `optional`：有新鲜图像就加入，缺失或过期时腕部mask置0。
- `required`：必须有新鲜腕部图像，缺失/过期时拒绝该次观测。
- `off`：关闭腕部，mask为0。

外部相机保持必需。两路RGB均为`[B,3,128,128]`，标记为`[B,2]`，顺序外部/腕部。
`camera_mask=[1,1]`代表双相机，`[1,0]`代表仅外部；标记不会检测画面冻结。
触觉`[B,10,16,24]`、状态`[B,26]`、6D输出保持。

完整双相机可选模式示例：

```bash
bash scripts/eef_bc.sh export /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip \
  local/eef_bc/bag004_cameras_optional_selected \
  --accept-future-state-proxy --wrist-camera optional
bash scripts/eef_bc.sh train --train local/eef_bc/bag004_cameras_optional_selected \
  --output local/eef_bc/policy_bag004_cameras_optional --overfit-smoke --steps 500
bash scripts/eef_bc.sh shadow --dataset local/eef_bc/bag004_cameras_optional_selected \
  --checkpoint local/eef_bc/policy_bag004_cameras_optional/policy.pt \
  --output local/eef_bc/shadow_bag004_cameras_optional_verified --loops 2
```

以上本机产物已存在，复跑请选择新的输出目录。模型自动从数据契约选择双相机结构，
无需再在train/shadow重复传开关；二者会拒绝不匹配的数据与模型。
要训练长期不用腕部的版本，把export改为`--wrist-camera off`并选独立数据/模型目录。
optional模型已在训练时模拟部分缺腕部，可使用同契约的缺腕部录包继续影子推理。
required与optional不能仅靠修改checkpoint元数据互换。

v2回放缓存只保存有效决策点实际需要的原始源帧，原始CDR、源时间、接收时间不变。
双相机样本哈希与全量导出一致；这里测试的是策略10Hz输入，不是原始全部采集流的吞吐。
检查报告`camera_mask_counts`：本包正常双相机两轮应为`{"1,1":140}`；
off或整路腕部缺失的optional场景为`{"1,0":140}`。
消息订阅仍会逐帧裁剪，未用预生成Tensor代替ROS输入。

腕部训练/推理都使用已约定ROI＋最近邻128缩放，人用看板保留Lanczos。
本包腕部近乎静止的采集问题没有修复，暂不以该包判断腕部对任务的实际收益。


## 7. 查看训练损失曲线

训练报告report.json的losses保存每25步及最后一步的随机mini-batch标准化动作MSE。
可直接从已有日志绘图，无需重训：

```bash
/usr/bin/python3 scripts/plot_eef_training.py \
  local/eef_bc/policy_bag004_cameras_optional/report.json \
  local/eef_bc/policy_bag004_cameras_off/report.json \
  --output local/eef_bc/bag004_training_curves.png
```

本机已生成上述对比图，两次训练目录也分别有training_curve.png；输出文件已存在时请换名。
图中21个点为实际记录，不平滑。该损失是无量纲训练batch误差，
不同于报告中的全段米/弧度RMSE，当前没有独立验证集曲线。
