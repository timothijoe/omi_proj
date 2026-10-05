# 完整 transition 的磁盘存储与双流导入

先 `source scripts/env.sh`，从 `omi_proj/` 执行。新增 `training.transition_replay`
复用现有 DiskHILReplayBuffer，提供完整数据导入、追加、检查及Python在线写入API。
不启动机器人或learner，不将当前BC数据自动转换成SAC经验。

## BC数据与RL数据的区别

BC通常只要求 `(observation, action)`；SAC要求
`(observation, accepted_command, reward, next_observation, terminated, truncated)`。
当前EEF BC的动作是未来位姿变化代理标签，不是已确认采用的控制命令；
samples.npz不能直接导入。不能用全零奖励、假next_observation或假结束标记补齐。
旧录包转换需要另核实命令来源、单位/坐标、时序和回合结果。

本入口JSONL一行一个完整transition，逐行读取，不将整个文件加载到内存。
大量图像转JSON体积和解析成本较高，实时Python接入应直接传NumPy数组给append。

## 固定契约

新建contract.json。下面仅是6D末端存储格式示例，不是当前历史policy完整输入，
也不是现场控制限位或已接入learner的配置。shape、bounds、版本应由真实任务确定。

```json
{
  "schema_version": 1,
  "observation_contract": "my-single-frame-camera-state-v1",
  "action_contract": "my-left-eef-base-m-rotvec-rad-v1",
  "reward_contract": "my-human-binary-success-v1",
  "action_semantics": "accepted_command",
  "observations": {
    "rgb": {"shape": [3, 128, 128], "dtype": "uint8", "low": 0, "high": 255},
    "state": {"shape": [7], "dtype": "float32", "low": -100, "high": 100}
  },
  "action": {"shape": [6], "dtype": "float32", "low": -1, "high": 1}
}
```

观测支持浮点/无符号整数，动作要求浮点向量。action_contract应明确对象、坐标、单位及表示。
契约字符串是生产方声明，不自行证明标定或设备执行。accepted_command指仲裁/执行边界
最终采用的命令，不是被覆盖的policy建议或反馈位移；采集侧仍须区分下发与反馈确认。

每条记录完整结构：

```python
record = {
    "observation_contract": contract["observation_contract"],
    "action_contract": contract["action_contract"],
    "reward_contract": contract["reward_contract"],
    "action_semantics": "accepted_command",
    "episode": "session-001/episode-001",  # 唯一UTF-8 ID，最多128字节
    "step": 0,
    "observation_time_ns": t,
    "next_observation_time_ns": next_t,  # >t，使用同一时间基准
    "observation": observation,
    "next_observation": next_observation,
    "executed_action": accepted_action,
    "action_source": "human",  # 或policy
    "reward": reward,
    "terminated": False,
    "truncated": False,
    "episode_success": True  # 初始离线成功示范必填；在线无需
}
```

离线初始示范每条需human和episode_success=true。成功由人工确认/检测器提供，
存储层检查声明但不验证物理成功。在线失败照常入池，人工纠正不要求最终成功。
存储检查时间先后，不负责传感器/命令配对、跨回合错配检测或重复导入去重。

## CLI：指定目录、导入与恢复

```bash
python -m omi_hil_rl.training.transition_replay --help
python -m omi_hil_rl.training.transition_replay create \
  --directory local/replay/my_task --contract contract.json --capacity 5000 \
  --offline-demo successful_demos.jsonl
python -m omi_hil_rl.training.transition_replay append \
  --directory local/replay/my_task --contract contract.json \
  --online online_transitions.jsonl
python -m omi_hil_rl.training.transition_replay inspect \
  --directory local/replay/my_task
```

输入参数可重复，create/append可混合导入。创建要求空目录，append不改变容量；
指定contract时按完整JSON检查一致性。离线human只进Demo；在线policy进RL，
在线human进两流，不受reward正负或最终成功影响。paused、缺字段、错误版本及代理标签拒绝。

导入错误会报告行号并停止，之前接受的行会保存，不是整文件事务。
报告imported是本次导入量，size/streams是ring仍保留的数据量。重复导入会重复保存。

## Python：在线入池、采样

```python
from omi_hil_rl.training.transition_replay import TransitionReplay

with TransitionReplay("local/replay/my_task", contract, capacity=5000) as replay:
    replay.append(record, origin="offline_demo")
    replay.append(online_record, origin="online")
    batch = replay.buffer.sample(64)  # 默认Demo32＋RL32，有放回
    print(replay.metadata(0))
    print(replay.report())

with TransitionReplay.reopen("local/replay/my_task", expected_contract=contract) as replay:
    replay.append(next_online_record, origin="online")
```

所有写入通过replay.append，buffer仅用于采样，不直接add/reset，否则元数据不对应。
在线actor需取得当前观测、最终采用命令、随后观测、奖励及结束事件后再append。
当前policy_gamepad没有调用此API；ROS配对、人工奖励/回合事件、命令确认和learner仍待实现。
selected_actions.jsonl不满足输入格式。动作按声明单位原样存储；接SB3需另做一致归一化，
不能直接挂到仅支持七维[-1,1]仿真动作的ExecutedActionSAC。

## 磁盘与内存边界

目录含transition_contract.json、manifest.json、各字段.npy及writer.lock。
观测/下一观测、动作、奖励、结束、两流标记、episode/step/时间均在memmap磁盘数组。
Python保留契约、ring位置及映射对象，采样生成临时索引和一个batch，至多预取一个batch。
OS会使用可回收页面缓存，不能保证RSS只占索引，也不是严格RAM上限。

容量满后覆盖旧transition和对应元数据，离线demo也可能覆盖；原始示范/录包应另存。
obs与next_obs分别保存，没有相邻图像或历史窗口去重。双RGB128单帧uint8的两份图像
每transition为196608字节，5万容量约9.83GB；整条10帧历史约98.3GB，另有触觉/状态。
保存历史还是单帧并按episode重建，应与未来learner输入契约一起确定。

单writer，不支持跨进程actor写/learner同时打开；分布式模式需队列/服务汇聚到learner。
正常close保存checkpoint，干净checkpoint可恢复；非正常退出dirty状态拒绝恢复。
没有断电日志、自动修复、异步写队列或冷盘/真机时限验收。
既有仿真用法见[disk_replay.md](disk_replay.md)。
