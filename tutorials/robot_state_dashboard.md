# 旧录包：视觉、触觉与机器人状态同屏

新版独立入口，旧 `view_observation_bag.sh` 和其冻结文件不变。
这是文字状态显示，不是URDF三维机器人，也不计算或伪造TCP位姿。
如需在RViz中央查看双臂模型，请使用独立的[3D回放入口](robot_3d_replay.md)。

## 启动（项目根目录）

先准备原稳定看板的SDK、基准、Python环境和匹配Jazzy的marvin_msgs overlay。
本机已在 `local/robot_state/viewer.env` 保存路径，无需手动export，直接运行：

```bash
bash scripts/view_observation_robot_bag.sh /home/zhoutong/omi_folder/representative_rosbag/october/record010/bag_001
```

换机器时，将 `scripts/robot_viewer.env.example` 复制到 `local/robot_state/viewer.env`，
编辑一次overlay位置即可；SDK默认使用项目的 `local/vendor/daimon_tactile`。
配置是可信本机Bash文件，不要source不可信来源的配置；local目录不进入Git。
环境变量仍可临时覆盖配置，`OMI_ROBOT_VIEWER_CONFIG` 可选择其他配置文件。
显式指定的配置不存在会报错。不要跨机器复制旧install；见[迁移清单](machine_transfer_checklist.md)。
用法：`BAG [RATE=1.0] [--no-rviz]`，例如 `BAG 0.5 --no-rviz`。
沿用原入口的 `OMI_TACTILE_PYTHON`、`OMI_TACTILE_BASELINE`、`OMI_TACTILE_RATE`、
`OMI_TACTILE_ROS_DOMAIN_ID`，默认localhost domain87。不要和旧入口同时在同一domain运行。

## 画面及时间含义

上部原视觉/触觉画面保持，底部增加340像素机器人状态区：

- 左右臂各7关节反馈，按消息定义的L/R顺序显示。
- A臂7关节目标，只读展示；A与L/R的对应未确认，不计算目标误差。
- 夹爪反馈与L夹爪命令，保持录制原值，不擅自解释为米/毫米或开合百分比。
- 源时间、相对参考时间的lag、VALID/STALE/WAITING；TCP明确NOT RECORDED。
- 角度等单位未核实，因此不转换为度，也不把effort解释为已标定力。

机器人记录使用非零header时间，否则回退bag接收时间并标注；无header的夹爪命令属于后者。
每次绘图以原dashboard的header为参考，独立选择各机器人流不晚于参考的最近记录，
超过0.25秒标记STALE。参考时间来自旧看板最近处理的图像消息，**不是统一曝光时刻**；
原相机、A/B触觉异步显示，不能声称所有图像和机器人数据精确同步。
原dashboard断流或其参考时间超过0.5秒不变也会使机器人区标STALE/PAUSED，
即使旧dashboard仍在重复发布画面。极低速回放也可能触发此提示，表示参考停止推进而非硬件故障。
旧看板自身的各图年龄提示仍需查看。循环/seek按参考时间重新查找，无跨圈保留机器人样本。

## 安全与资源边界

启动前从原bag离线解码四个机器人topic，生成小型JSON时间线缓存；不创建机器人命令发布器。
实际rosbag播放器仍复用原入口的图像白名单，**不会回放joint_cmd_A或gripperValueL**。
输出唯一新增ROS topic为 `/omi/observation_robot/dashboard`（rgb8）。只启动localhost可视化，
不连接机器人、不发送运动、也不新增TCP录制。

时间线缓存位于 `local/robot_state/replay_cache/`，按源路径、metadata哈希、分卷大小/mtime和版本区分。
首次读取文件级zstd时在私有临时目录解压，源目录不变，需要至少一个解压分卷的空间；
后续复用缓存。支持旧MCAP及file-zstd MCAP；其他存储类型本入口明确拒绝。
时间线一次加载到内存，适合目前短示教包，超长录制需后续改为索引查询。
当前缓存指纹不是源文件逐字节完整性校验。缺字段显示WAITING；缺全部有效机器人数据则启动失败。

新增实现与测试：`real/robot_state_panel.py`、`tests/test_robot_state_panel.py`。
修改前回退点：`32c2a11`。
