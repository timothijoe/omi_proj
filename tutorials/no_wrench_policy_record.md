# 当前操作：无六维力/力矩模型推理与观测录制

阶段证据、三轮训练对照和未解决事项见[诊断记录](../docs/agent/training/chronicles/2026-10-05-policy-input-audit-no-wrench.md)。
当前模型关闭的是**wrench六维力/力矩**，不是所有触觉：触觉网格、双相机和EEF十帧历史仍需发布。
离线重放仍有后退，不能视为可以稳定插USB的模型。

## 1. 当前模型与默认值

入口`run_no_wrench_policy_record.sh`默认加载：

```text
local/passive_bc_20261005_no_wrench_no_third_train_v1/actor_train_best.pt
```

这是第1000步训练集最佳模型，不是该目录`actor.pt`（验证选择停在第0步）。
默认CUDA、domain13、手柄`/dev/input/js0`、raw EEF、policy-scale=1.0。
手柄与模型上限5mm/s、5°/s，10Hz动作；候选年龄拒绝默认off，外部RGB年龄500ms。
RB按住优先人工，松开只接收松开后的新候选；断开手柄暂停；不重复执行同一个候选。
推理入口默认将键码314设为独立回位键：单按一次即可从当前位姿返回home，不需同时按RB。
取消候选年龄拒绝意味着旧候选可能延迟执行一次，不是无风险模式。

## 2. 先预览并录制

在项目根目录执行，输出目录必须尚不存在（重跑换后缀，不删除旧记录）：

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/run_no_wrench_policy_record.sh \
  --output local/policy_gamepad/no_wrench_record_02 \
  --duration 3600
```

不加`--execute`时，模型和RB仲裁正常运行，但不发布最终机器人动作。
若旧版启动时在`load_wrench_policy`报`unsupported live passive wrench BC checkpoint contract`，
原因是当前采集按键默认值改变，而此检查点保留训练时的成功键307。加载器已兼容这一已知历史按键配置，
仍逐项核对观测、动作尺度及SDK约定；本机默认`actor_train_best.pt`已实际加载验证为第1000步、`wrench_history=False`。
更新源码并退出旧进程后重试；该错误发生在创建输出目录和发布者之前，目录不存在时可复用原路径。
确保没有其他独立手柄/策略程序同时控制机器人；本脚本不能阻止其他进程运动。
正常时应看到完整历史和`candidate_gate=ok`；关注模型原始dx，不把`paused_no_policy`零动作误认为网络零输出。
无wrench模型的manifest应有`wrench_input_enabled=false`，topics里没有wrench。

## 3. 执行模式与手柄

当前建议先用预览定位方向问题。需要执行时，在已确认现场条件后使用**新输出目录**并加`--execute`。
启动检查会打开手柄核对轴和RB、读取`/delta_ctrl_node/get_parameters`、核对实际订阅。
`--manual-topic auto`可自动匹配接收端的`/omi/controller_test/decision`或常规手动话题，
不需要仅为话题名称重启接收端。无法发现服务/订阅、手柄失败或显式话题不匹配时拒绝发布。
启动时检查不等于持续监控，也不证明SDK执行成功；不要运行中重配接收端。

按住RB（311）再操作摇杆；不是摇杆一动就自动接管。
单按键码314触发返回home；返回时由手动通道发送增量，覆盖模型和摇杆动作，手柄断开会取消。
回位键按住不重复触发；返回结束或失败后，松开314才重新等待新的模型候选。
启动后先在终端核对`返回触发键码=314`及`按下按钮=[314]`，不同手柄可用`--home-button-code`覆盖。
执行无额外确认：输入齐全、手柄连接且RB松开时可能立即运动。
软件零动作/退出不等于硬件急停，接收端工作空间和现场安全要求仍适用。
峰值触觉保护与网络wrench输入是两回事：接收端保护默认关闭，关闭网络分支不会替你更改它。

## 4. Ctrl+C与保存位置

数据在推理过程中持续后台写盘。按Ctrl+C停止产生新动作后，等待终端“观测保存结果”再退出。
重复Ctrl+C不会中断正常收尾；最多60秒等待，永久磁盘卡死、断电或SIGKILL不能保证完整。

```text
输出目录/
  session.json                         启动参数与手动话题检查结果
  selected_actions.jsonl               实际选择/发布动作、RB状态
  policy/
    manifest.json                     检查点路径/哈希、归一化、输入设置
    predictions.jsonl                 每次决策的输出或拒绝原因
    report.json                       运行总结
    observations/
      <reference_ns>_<epoch>.npz       实际推理窗口、输出、metadata
      summary.json                    saved/dropped/errors/flushed/complete
```

无wrench版本的npz不含wrench字段；包含双相机裁剪图、触觉网格、EEF、mask和原始m/rad预测。
保存归一化前的网络输入，归一化参数另存manifest；保留对应checkpoint才能准确重放。
无有效窗口时不生成假观测，只记录原因。最终动作通过`selected_policy_reference_ns`关联观测时间。
`saved>0`才有数据；`complete=true`且`dropped=0`、`errors=[]`表示已提交记录完整落盘，
不是所有传感器时刻均有记录，也不是动作成功证据。

默认压缩容量10GiB，队列16窗口；队列满丢帧并报告，磁盘/容量错误停止保存新窗口但控制继续。
可追加`--record-max-gb 20`，或按需调整`--duration`，不要用长时录制掩盖存储不足。

## 5. 与其他入口区分

| 脚本 | 默认模型 | 连续观测录制 |
| --- | --- | --- |
| `run_wrench_policy_gamepad.sh` | 原带wrench第200步 | 默认否 |
| `run_wrench_policy_record.sh` | 原带wrench第200步 | 是 |
| `run_no_wrench_policy_record.sh` | 新无wrench第1000步训练最佳 | 是 |

都默认预览，显式`--checkpoint`可覆盖模型路径；不要因为名字含wrench就误判实际输入，检查点recipe决定网络分支。
`--candidate-expiry on`恢复候选年龄拒绝；`--rgb-max-age-ms 250`恢复外部RGB旧门槛。
完整机制与带wrench版本说明见[通用教程](wrench_policy_gamepad.md)。
