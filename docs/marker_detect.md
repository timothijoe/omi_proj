# AprilTag 位姿检测、手眼标定与相对位姿跟随

更新于 2026-10-17。tag10/tag12 已完成 ROS 图像接入、LB 组合键控制、独立窗口与异步 RL 集成；已在本机采集手眼标定并进行真机跟随试用。根据振荡日志降低了增益与步长，增加独立死区和恢复阈值，尚无独立测量的最终跟随精度或稳定性验收结果。

本页前半部分介绍原 ID 0–7 标记板工具；tag10/tag12 用户可直接查看[跟随数据流与控制参数](#tag-follow)、[标定文件与本次结果](#tag-handeye-files)。启动命令见[操作教程](../tutorials/marker_detect.md#tag-follow)，训练内使用见[异步 RL 教程](../tutorials/async_rl.md#tag-follow)。

实现脚本：[hand_eye_calibration.py](../ros2/marker_detect/hand_eye_calibration.py)。运行步骤见[marker 检测教程](../tutorials/marker_detect.md)，手眼方程推导见[原理说明](../ros2/marker_detect/hand_eye_calibration_principle.md)。

## 数据流与坐标

脚本订阅 RealSense ROS 2 彩色图像 `/camera/camera/color/image_raw` 和对应的 `/camera/camera/color/camera_info`。彩色 `CameraInfo.k`、`d` 用于 AprilTag 角点的 PnP 解算；默认还订阅 `/camera/camera/aligned_depth_to_color/image_raw`，仅把与彩色帧时间相差不超过 100 ms、尺寸相同的深度用于显示和保存参考值。没有深度图仍可解算位姿。深度值不参与 PnP 或手眼求解，也不会作为采样拒绝条件。

板参数固定在脚本的 `BOARDS` 中：45 mm 外框使用 tag ID 0–3，50 mm 外框使用 ID 4–7；两组的 tag 位图边长均为 20 mm。每组至少检测到 2 个 tag 才进行 PnP。打印应使用仓库内的 [A4 标记板](../ros2/marker_detect/apriltag_45_50mm_A4.pdf)，保持 100% 比例并贴平；打印缩放会直接造成平移尺度错误。A4 文件重复印了三行相同 ID，检测器按图像位置把每行分开，优先选取标签数较多且靠近画面中心的那组，并检查重投影误差不超过 5 px。当前 PDF 的 tag 图案与 OpenCV 字典生成方向相差 180°，程序会尝试两种角点对应并选择误差较小的位姿。

每组单独输出 `T_cam_board`：它把该组 marker 中心坐标系中的点变换到**彩色相机光学坐标系**。板中心为原点，从板正面看 `+x` 向右、`+y` 向上、`+z` 垂直板面朝外。`T_cam_board[:3, 3]` 的单位是米，程序显示和 JSON 的 `translation_mm` 用毫米；`rpy_deg` 为 ZYX 欧拉角，单位度。`dist_to_optical_center_mm` 是平移向量的欧氏长度，不是仅沿光轴的 Z 深度。JSON 的 `camera_frame` 取自彩色 `CameraInfo.header.frame_id`。

## 两种运行方式

- `--cam-only`：只计算 marker 相机位姿；图像窗口中按 `s` 对连续帧取中值平移、平均旋转后写入 `handeye_result/cam_only_samples.json`。按 `d` 删除本次运行的上一条，按 `c` 查看汇总。
- `--cam-only --headless`：适合 SSH。完全不调用 OpenCV 窗口，每秒输出检测到的 XYZ、RPY、光学中心距离、tag 数和重投影误差；默认每 2 秒自动采一组并追加保存。`--capture-interval` 改间隔，`--max-samples` 限制本次样本数，Ctrl+C 正常退出。没有可用显示服务时，`--cam-only` 也会自动进入此模式；SSH 中建议显式传入 `--headless`。

需要 eye-to-hand 外参时，图形模式中使用 `--ros2` 读取机器人 `base_link <- tool0` TF，采集多组末端位姿与 `T_cam_board`，按 `c` 求 `T_base_cam`。`--manual` 和 `--ros1` 只改变末端位姿来源，**相机图像仍必须来自 ROS 2 话题**。当前无界面模式仅支持 `--cam-only`；手眼标定采样仍需要窗口操作。

## 原 ID 0–7 标记板工具的验证边界

已用合成 AprilTag 图像验证角点检测、PnP 平移方向与米/毫米转换；用构造的 ROS 消息验证彩色内参、图像与对齐深度解码；用模拟相机验证无窗口自动采样和 JSON 保存。尚未在本机用真实 RealSense 与机械臂实测位姿精度或手眼外参。

<a id="tag-follow"></a>

## tag10/tag12 默认相对位姿跟随

异步 RL 的 `periodic_training_v1` 入口现也支持这些组合键，通过 `TagFollowSession` 复用 Actor 的 ROS 节点与输出通道，后台检测不创建额外发布者。活动回合跟随时暂停策略、暂停回合计时，控制切换递增 `control_epoch`，回放转换无条件排除跨该边界的 transition。完整启动命令见[异步 RL 教程](../tutorials/async_rl.md)。以下独立入口不应与 RL 同时运行。

入口为 `ros2/marker_detect/tag_follow_tag_v2.py`，控制逻辑为 `src/omi_hil_rl/real/tag_follow.py`。图像订阅 `/camera/camera/color/image_raw`，内参订阅 `/camera/camera/color/camera_info`，不再直接打开 RealSense，也不依赖缺失的 `handeye_solver`。tag10 的物理边长为 51 mm，tag12 为 64 mm，字典为 tag36h11；原来的 ID 0–7 标记板不适用于此跟随脚本。

| 实现 | 职责 |
| --- | --- |
| [tag_follow_tag_v2.py](../ros2/marker_detect/tag_follow_tag_v2.py) | 独立图像窗口、手柄/键盘操作与指令发布 |
| [tag_follow.py](../src/omi_hil_rl/real/tag_follow.py) | 相对目标、X/Z 变换、增益、限幅及独立死区 |
| [tag_follow_camera.py](../src/omi_hil_rl/real/tag_follow_camera.py) | ROS 彩色图/内参订阅及本地接收时间戳 |
| [tag_follow_session.py](../src/omi_hil_rl/real/tag_follow_session.py) | 训练进程内的后台检测、保存与跟随状态 |
| [tag_handeye_calibration.py](../ros2/marker_detect/tag_handeye_calibration.py) | tag10 多姿态采样窗口与离线求解入口 |
| [tag_handeye.py](../src/omi_hil_rl/real/tag_handeye.py) | 图像/TCP 配对、静止检查、X/Z 解算及质量校验 |

设 `B10=T_cam_tag10`、`B12=T_cam_tag12`。LB（Linux 按键码 310）+305 保存 `D=inv(B10) @ B12` 到 `handeye_result/tag_follow_default.json`，同时停止跟随。文件明确记录标签尺寸、变换方向和米制单位，重启自动读取但不自动运动。LB+304 启动持续跟随，再按一次停止；松开组合键后继续跟随。RB、键盘 s、手柄断开会停止，重新连接不会自动启动。x 使用当前相对关系临时跟随，不覆盖默认文件，也不影响下一次 LB+304 使用的默认关系。

控制使用 `X=T_base_link_cam` 和 `Z=T_TCP_tag10`，平移单位米，TCP 必须与接收端当前控制点一致：

```text
T_base_TCP_current = X @ B10 @ inv(Z)
T_base_TCP_desired = X @ B12 @ inv(D) @ inv(Z)
p_error = p_desired - p_current
R_error = R_desired @ R_current.T
```

沿用左臂 A 的安装旋转 `Rx(-90°)`，将误差转换到 SDK 臂基坐标系。终端 `error xyz/RxRyRz` 显示完整平移误差（mm）和旋转误差向量（degree）；不能直接相减欧拉角。发布消息为 `std_msgs/Float64MultiArray`，`data=[dx,dy,dz,dA,dB,dC]`，10 Hz，单位 mm/degree，后三维满足 `R=Rz(C)Ry(B)Rx(A)`。接收端应使用左臂 A、`delta_frame=base` 和匹配的 TCP/UserFrame。

跟随比例增益现为平移/旋转各 0.08（原为 0.3），每轴每周期平移最大 0.5 mm、旋转 ABC 最大 0.2°（原为 2 mm/1°）；10 Hz 下对应每轴最大 5 mm/s、2°/s。平移与旋转分别按各自三维误差向量的模长判断死区：平移≤2.5 mm 时只将平移输出归零，旋转≤0.8°时只将旋转输出归零。各部分停止后，分别需要误差>3.5 mm 或>1.2°才恢复修正；中间区域保持停止，避免阈值附近反复启停。开始新一次跟随会重置此状态。两部分都停止时显示 `HOLDING`，持续发布零增量并监测目标；目标移出恢复阈值后继续跟随，不自动退出跟随模式。

| 项目 | 平移 | 旋转 |
| --- | --- | --- |
| 比例增益 | 0.08 | 0.08 |
| 每轴每周期最大指令 | 0.5 mm | 0.2°（SDK ABC） |
| 进入保持的条件 | 误差向量模长≤2.5 mm | 旋转向量模长≤0.8° |
| 保持后恢复修正 | 模长>3.5 mm | 模长>1.2° |

例如平移误差 1 mm、旋转误差 2°时，只发旋转修正；平移误差 5 mm、旋转误差 0.3°时，只发平移修正。保持状态中间区域的输出为零，而原始误差仍完整记录。参数定义在共用控制模块中，独立窗口和 RL 内置跟随均需重启后加载代码修改。

| 状态 | 含义 |
| --- | --- |
| `STOPPED` | 未启用跟随或已显式停止，输出为零 |
| `TRACKING` | 跟随已启用，平移/旋转按各自误差决定是否修正 |
| `HOLDING` | 两部分均处于保持状态，输出为零，继续监测目标 |
| `PAUSED` | 跟随已启用但标签/接收后时效无效，输出为零，观测恢复后继续 |

这些是发送端状态；`HOLDING` 说明当前输出为零，不是对真实机械臂已完全静止的独立测量。

每次检测要求两标签同帧有效、未被跳变过滤器拒绝、边长至少 20 px。跟随控制使用图像订阅回调入口的本地单调时间戳（`time.monotonic()`），接收后年龄须小于 120 ms，包含图像解码与检测耗时。位姿滤波也使用同一接收时钟。`header.stamp` 不用于跟随时效判定；日志 `receive_age_ms` 表示接收后的年龄，不表示拍摄到接收的端到端延迟。标签失效或相机断流发送零，跟随状态保持暂停，有效画面恢复后继续。原始 header 时间仍保留给独立手眼标定的图像/TCP 配对。

调参回归使用理想 10 Hz BASE 增量响应、非零 TCP/tag 偏移、小幅观测噪声及 0/400/600/800 ms 延迟，检查最终输出归零，以及目标移动后恢复并再次归零。这是简化离线模型，不代表真实机械臂动力学或实机收敛验收。

无标定时可以检测和保存默认关系，但禁止开始跟随。现有 ID 0–7 标定结果不能直接改字段名充当 X/Z。检测到另一发布者占用 `/omi/action/decision` 时退出；本脚本独占该策略输出，不同时运行手柄仲裁或策略发布程序。退出时发送零增量，异常断进程仍由接收端断流超时保护。运行步骤见[教程](../tutorials/marker_detect.md#tag-follow)。

<a id="tag-handeye-files"></a>

## 标定文件、默认位姿与现场结果

| 文件 | 内容 | 生成方式 |
| --- | --- | --- |
| `ros2/marker_detect/handeye_samples_日期_时间.json` | 多姿态原始样本，含 A/B 矩阵与配对信息 | 标定窗口 S / LB+305，每次采样自动保存 |
| `ros2/marker_detect/handeye_result.json` | X/Z、质量阈值、残差、内参及样本来源 | 标定窗口 C / LB+304 或离线 `--solve-samples`，通过检查才写入 |
| `ros2/marker_detect/handeye_result/tag_follow_default.json` | 两标签要保持的相对关系 D | 跟随窗口 LB+305 |

标定窗口的 LB+305 是采样、LB+304 是求解；跟随窗口的同一组合键分别是保存默认关系和开始/停止跟随。原始样本不能只改文件名就作为 X/Z 使用。相机、标签安装或受控 TCP 改变后需要重新标定。

tag10 标定满足 `A_i Z = X B_i`：A 来自 `/tj/info/eef_left` 的 `base_link <- TCP` 实际反馈，B 是相机中的 tag10 位姿。用 header 的拍摄时间匹配 TCP 历史（误差≤50 ms），每个静止姿态至少10帧且跨度≥0.7秒，至少15个不同姿态。求解检查多轴旋转覆盖、训练样本残差与三折留出误差；详细采样条件见[首次标定教程](../tutorials/marker_detect.md#tag-handeye)。

当前软件验收阈值：平均/最大平移残差≤3.5/10 mm，平均/最大旋转残差≤1/3°，留出验证 RMS≤5 mm/2°。平均平移阈值按用户要求由3 mm调整为3.5 mm；该门槛是本工具的验收配置，不是通用精度标准，每份结果在 `quality_limits` 中记录实际值。

2026-10-17 本机结果：第二轮21个样本，按用户要求在副本中剔除最大平移残差对应的原第15条，用剩余20条求解。平均/最大平移残差为 **3.03/6.60 mm**，平均/最大旋转残差为 **0.89/1.97°**，三折留出 RMS 为 **4.22 mm/1.05°**，通过调整后的检查。结果写入 [handeye_result.json](../ros2/marker_detect/handeye_result.json)，保留原始数据、剔除记录和阈值变更信息。残差是内部一致性指标，不等于真实闭环定位精度。

现场旧参数试用出现误差反复变号与限幅输出；停止后的只读采样中，相对位姿波动最大约0.34 mm/0.045°，消息 header 与本地时钟差中位数约422 ms，本地接收后处理年龄约9 ms。前者用于延迟诊断，后者用于当前时效检查，两者不能混作同一个延迟。依据该现象降低增益/步长并引入独立死区。最新相关软件回归83项通过，覆盖六轴方向、TCP偏移、按键、接收时钟、死区、恢复与延迟模型；新参数已在现场启动试用并按用户要求正常退出，但尚未形成独立的精度/稳定性量化验收。
