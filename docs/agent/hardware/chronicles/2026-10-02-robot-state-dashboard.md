# 2026-10-02：旧录包机器人状态同屏

用户要求先提交当前状态，再实现机器人状态显示。先提交全部当时非忽略改动，
回退点 `32c2a11`；确认工作区干净后开始实现。不把本地SDK、录包、venv等忽略资源加入Git。

新增 `view_observation_robot_bag.sh`、独立RViz配置和 `robot_state_panel.py`。
离线读Marvin关节反馈/目标、夹爪状态/命令，缓存时间线，追加到原视觉触觉画面底部。
关节显示录制原值与L/R索引；不臆测单位或A侧映射，不计算TCP，明确未记录。
四类流按原dashboard参考header选择过去最近样本，显示lag与header/bag_receive来源；
过期、缺失及参考停滞分别标识，支持循环回放，非多模态曝光精确同步。

机器人命令只离线解码，无命令publisher；原播放器仍只播放图像白名单。
旧稳定入口及8个受保护文件哈希未改变。

验证：

- 隔离ROS自动pytest插件后，全套111 passed、5 skipped；针对新增逻辑与冻结文件5 passed。
- record010四类状态共21866条解码并缓存，私有临时解压，不修改原包。
- domain94独立headless回放42秒，2倍速，收到355帧1080×1792合并画面，检测到循环，
  未发现 `/tj/control/` 话题；退出无需强杀，检查无相关残留进程。
- 检视 `local/robot_state/preview.png`：相机/触觉与文字区均正常。
  运行日志与报告位于同目录；未交互启动RViz GUI、未连接设备。
- 后续补充参考header不变时的STALE/PAUSED判定，防止旧dashboard重复发布掩盖暂停。

用法与边界见[教程](../../../../tutorials/robot_state_dashboard.md)。新改动未自动提交。

## 后续：本机配置自动加载

用户希望不再每次export路径。新入口自动读取Git忽略的
`local/robot_state/viewer.env`，本机已配置Marvin overlay和项目内SDK；提供可提交的
`scripts/robot_viewer.env.example`供换机编辑，环境变量仍可覆盖。旧入口不改。
补充配置优先级/路径含空格/缺失配置测试，并清除两个路径环境变量实测无界面启动。
限时退出暴露的ROS发布/关闭竞争按context状态处理，正常运行中的RCLError仍向外抛出。
