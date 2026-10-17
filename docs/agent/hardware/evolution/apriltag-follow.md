# AprilTag 位姿估计与视觉跟随

2026-10-17后续更新：当前工作区已实现ROS相机、手眼标定、LB组合键及独立/异步RL跟随，共用 `real/tag_follow*.py` 控制模块；不再是仅迁入状态。最新接口、参数、现场结果和验证限制统一见[AprilTag专题](../../../marker_detect.md)及[开发快照](../../../oct17_development_checkpoint.md)。以下内容保留本日最初原样迁入阶段的职责、来源与当时待办；其中缺少handeye_solver/标定及旋转转换问题不能直接当作最新实现状态。

更新于 2026-10-17。跟随入口已适配 ROS 图像、手柄默认位姿、异步 RL 集成及 tag10 多姿态标定，已进行现场采样和独立跟随试用。根据振荡反馈下调增益与步长，并增加独立死区和恢复阈值；尚未完成独立的闭环精度量化验收。[原始迁入证据](../chronicles/2026-10-17-apriltag-follow-migration.md)保留迁入时状态，当前行为以本页及技术说明为准。

## 文件与职责

- [tag_pose.py](../../../../ros2/marker_detect/tag_pose.py)：基于 NumPy、OpenCV、pupil_apriltags 的标签位姿估计，包含角点精修、IPPE 双解消歧、SE(3) One-Euro 滤波、跳变抑制及可选对齐深度辅助。
- [tag_follow_tag_v2.py](../../../../ros2/marker_detect/tag_follow_tag_v2.py)：订阅 ROS 彩色图像和 CameraInfo，估计末端 tag10（51 mm）与目标 tag12（64 mm），LB+305 保存默认关系，LB+304 开始/停止跟随。向 `/omi/action/decision` 发布 10 Hz 六维增量（mm/ABC 度）；保留 x 临时记录并跟随、s 停止、q/ESC 退出。核心控制逻辑在 [tag_follow.py](../../../../src/omi_hil_rl/real/tag_follow.py)。
- [tag_handeye_calibration.py](../../../../ros2/marker_detect/tag_handeye_calibration.py)：只读采集 tag10 与 `base_link <- TCP` 多姿态样本，按时间戳配对、检查停稳及覆盖，求解 X/Z；通过残差及留出校验后写入结果。
- [tag_follow_session.py](../../../../src/omi_hil_rl/real/tag_follow_session.py)：Actor 中的后台检测与跟随状态；不单独创建发布者，复位动作不入训练回放。

两个入口与已有标定工具同放 `ros2/marker_detect/`，没有替换原标定实现。异步 RL 周期会话也已接入组合键，使用 `TagFollowSession` 后台检测并共享 Actor 输出；跟随仅作复位，不进入训练回放，详见[训练入口教程](../../../../tutorials/async_rl.md)。独立运行方式及坐标约定见[教程](../../../../tutorials/marker_detect.md)和[技术说明](../../../marker_detect.md)。

## 当前配置与验证范围

1. 当前 X/Z 已保存到 `ros2/marker_detect/handeye_result.json`：第二轮21条样本剔除原第15条后以20条求解，平均平移残差3.03 mm、最大6.60 mm、留出 RMS为4.22 mm/1.05°。按用户要求，平均平移门槛从3改为3.5 mm，其余门槛不变；结果保留剔除及阈值来源。Z 对应采样时的受控 TCP；安装或 TCP 配置改变后重标。原 ID 0–7 标记板结果不可直接替代。
2. 已在 `local/cuda-env` 安装 `pupil-apriltags 1.0.4.post11` 并完成真实检测库的合成标签验证；独立 `.venv` 若要运行仍需安装检测库。ROS、OpenCV、NumPy 和项目依赖必须在同一 Python 运行环境可用。
3. 当前增益为平移/旋转各0.08，每轴每周期最大0.5 mm/0.2°；平移≤2.5 mm、旋转≤0.8°时独立归零，保持后分别超过3.5 mm、1.2°才恢复。`HOLDING` 表示持续监测且两部分输出为零。独立和 RL 入口共享实现。
4. 跟随时效与滤波使用本地订阅回调单调时间，接收后120 ms超时归零；header仅保留给标定配对和诊断。接收后年龄不包含传输滞后。默认停止，标签失效/拒绝归零，手柄断开停止，退出归零。独立脚本需要独占策略输出，训练内使用 Actor 已有发布器。
5. 当前 Xbox 最后一次启动位于 js0，之前曾位于 js1；按设备名称确认，避免误选 SpacePilot。新参数已在现场启动试用并正常退出，但不能把内部校验或离线模型收敛当作真实闭环精度验收。

## 来源与验证

原件来自 `/home/zhoutong/Downloads/oct17/`，仍保留。冻结备份位于 `local/vendor/apriltag_follow/oct17/`，`source_sha256.json` 记录来源、正式路径、字节数及 SHA-256。今后适配维护正式路径，备份保留迁入时版本。

原样迁入时两份正式文件与来源、备份逐文件 SHA-256 一致；后续修改正式跟随脚本，冻结备份不变。最新增益/死区相关回归83项通过，包括方向、TCP偏移、按键、接收时钟、独立停止/恢复，以及0–800 ms延迟的简化闭环模型；标定求解另有18项无硬件测试。现场原始样本、X/Z质量指标及诊断解释见[技术说明](../../../marker_detect.md#tag-handeye-files)。
