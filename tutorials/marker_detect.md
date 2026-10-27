# AprilTag：位姿记录、手眼标定与手柄跟随

tag10/tag12 用户先看[独立跟随启动](#tag-follow)；首次使用或安装位置改变时，先做[多姿态手眼标定](#tag-handeye)。训练过程中使用[异步 RL 内置跟随](async_rl.md#tag-follow)，不要同时启动独立脚本。

以下前半部分介绍原 ID 0–7 标记板工具。从仓库根目录 `omi_proj/` 执行命令，脚本订阅 ROS 2 RealSense 彩色图像和内参，求出两组 marker 各自相对于**彩色相机光学中心**的位姿。SSH 无桌面时使用 `--headless`，不需要 X11 转发。算法、单位和验证范围见[技术说明](../docs/archive/marker/records/marker_detect.md)。

## 准备图像与标记板

系统 Python 需要 `rclpy`、`sensor_msgs`、`cv_bridge`、NumPy 和带 `aruco` 模块的 OpenCV。先启动 RealSense ROS 2 驱动，并保证脚本与驱动处于同一个 `ROS_DOMAIN_ID`。本项目的默认相机话题如下：

| 用途 | 默认话题 | 必需 |
| --- | --- | --- |
| 彩色图 | `/camera/camera/color/image_raw` | 是 |
| 彩色内参 | `/camera/camera/color/camera_info` | 是 |
| 对齐到彩色图的深度 | `/camera/camera/aligned_depth_to_color/image_raw` | 否 |

若由本项目的传感器采集入口启动相机，先按[传感器采集教程](sensor_collection.md)配置并启动 `live`。若单独启动官方驱动，可在另一个终端运行：

```bash
ros2 launch realsense2_camera rs_launch.py \
  camera_namespace:=camera camera_name:=camera \
  enable_color:=true enable_depth:=true align_depth.enable:=true
```

检查订阅源：

```bash
ros2 topic list | grep /camera/camera
ros2 topic hz /camera/camera/color/image_raw
ros2 topic echo /camera/camera/color/camera_info --once
```

将 [apriltag_45_50mm_A4.pdf](../ros2/marker_detect/apriltag_45_50mm_A4.pdf) 按 **100% 比例**打印，裁下一组 45 mm 和 50 mm marker，平整地固定。脚本识别 45 mm 组 ID 0–3 和 50 mm 组 ID 4–7；每组至少要看到 2 个 tag。板坐标系原点为该组中心。A4 页上三行重复 ID 会按空间位置分组；若整页同时入镜，优先取靠近画面中心且标签完整的一行。

## SSH：不打开图像窗口

```bash
python3 ros2/marker_detect/hand_eye_calibration.py --cam-only --headless
```

检测到 marker 后，终端每秒打印 `XYZ`（毫米）、`RPY`（度）、光学中心距离（毫米）、tag 数和重投影误差。默认每 2 秒对连续帧求平均并把一条记录写入运行目录下的 `handeye_result/cam_only_samples.json`；按 `Ctrl+C` 退出。比如每 5 秒采样，保存 10 条后自动退出：

```bash
python3 ros2/marker_detect/hand_eye_calibration.py \
  --cam-only --headless --capture-interval 5 --max-samples 10
```

如果只需彩色图求位姿、没有对齐深度话题，可以关闭深度订阅：

```bash
python3 ros2/marker_detect/hand_eye_calibration.py \
  --cam-only --headless --depth-topic ''
```

文件中每条记录包含 `camera_frame`，以及每组 marker 的 `T_cam_board` 4×4 矩阵、`translation_mm`、`rpy_deg`、`dist_to_optical_center_mm`、`reproj_px`、`n_tags` 和可选的 `depth_mm`。矩阵平移列使用**米**，毫米字段供直接读数。`depth_mm` 是对齐深度在 marker 附近的参考值，不参与位姿求解。可以用 `--out-dir 目录` 改保存位置。

## 有桌面时查看图像

```bash
python3 ros2/marker_detect/hand_eye_calibration.py --cam-only
```

图像窗口会显示每组 marker 的 XYZ、RPY、距离和重投影误差。点选窗口后按 `s` 保存一条平均位姿，`d` 删除本次运行的上一条，`c` 查看汇总，`q` 或 `Esc` 退出。脚本会在创建窗口前检查 OpenCV 的图形后端；没有可用显示服务时自动改用无界面模式。通过 SSH 时显式加 `--headless` 更清楚。

## 自定义话题与排错

驱动使用其他命名时，传入 `--color-topic`、`--camera-info-topic`、`--depth-topic`。`CameraInfo` 必须对应彩色图像，分辨率要一致；深度话题必须是**对齐到彩色图**的版本。脚本等待彩色图及匹配内参 5 秒后会报告超时。先用 `ros2 topic list`、`ros2 topic hz` 核对话题，并检查 SSH 会话和相机驱动的 `ROS_DOMAIN_ID`、ROS 网络发现配置。无窗口模式会每秒显示两组板各自检出的 tag 数；50 mm 组不足 2 个时，检查 ID 4–7 是否清晰入镜，若提示角点几何或重投影误差不合格，检查打印平整度、遮挡、图像模糊与内参。

`qt.qpa.xcb: could not connect to display` 表示当前会话无法创建图像窗口；使用 `--headless` 即可。`ROS_LOCALHOST_ONLY is deprecated` 是 ROS 2 环境变量警告，与 Qt 显示失败无关。当前无窗口模式仅用于 `--cam-only` 位姿记录；需要机器人 eye-to-hand 标定时参照[原理说明](../ros2/marker_detect/hand_eye_calibration_principle.md)，在有显示服务的环境中运行交互式采样。

<a id="tag-follow"></a>

## tag10/tag12：手柄默认位姿跟随

如果同时运行 `bash scripts/run_async_rl.sh`，使用其[内置跟随功能](async_rl.md#tag-follow)，不要另开下面的独立脚本。训练入口支持 `--tag-follow-calibration`，共享 Actor 发布器，并在跟随期间暂停策略及回合计时、排除跟随训练样本。

这是独立入口 `tag_follow_tag_v2.py`，使用末端 tag10（51 mm）、目标 tag12（64 mm），两者均为 tag36h11，尺寸指黑框外沿。需要 ROS 2、cv_bridge、NumPy、OpenCV、pupil_apriltags 和项目 Python 依赖。本机已在 `local/cuda-env` 安装检测库；下面使用该环境和 `scripts/env_ros.sh` 加载依赖。图像由已运行的 ROS 相机驱动提供，接收端需另行启动。

先确认 Xbox 的设备号（拔插或同时连接 SpacePilot 后，js0/js1 可能互换）：

```bash
python3 - <<'PY'
from pathlib import Path
for device in sorted(Path('/sys/class/input').glob('js*')):
    print('/dev/input/' + device.name, (device / 'device/name').read_text().strip())
PY
```

找到名称包含 `Microsoft X-Box 360 pad` 的设备，将下面 `--device` 改为对应路径。最后一次启动使用 js0；它不是固定设备编号。

使用当前标定启动图像窗口：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source scripts/env_ros.sh
export ROS_DOMAIN_ID=13
local/cuda-env/bin/python ros2/marker_detect/tag_follow_tag_v2.py \
  --calibration /home/zhoutong/omi_folder/omi_proj/ros2/marker_detect/handeye_result.json \
  --device /dev/input/js0
```

相机、机械臂接收端与本脚本必须处于同一个 ROS domain；上例 13 应与实际配置保持一致。SSH 加 `--headless`；只用键盘时加 `--no-gamepad`，不能与 `--headless` 同时使用。默认订阅 `/camera/camera/color/image_raw` 和 `/camera/camera/color/camera_info`，可分别通过 `--image-topic`、`--camera-info-topic` 修改。

启动日志应显示 X/Z 已加载，以及增益0.08、步长0.5 mm/0.2°；初始为 `STOPPED`。窗口显示图像、标签编号/边框/坐标轴和控制状态，终端显示完整六维误差及实际发送增量。

| 操作 | 行为 |
| --- | --- |
| LB+305（B） | 两标签有效时保存默认相对位姿，并停止当前跟随 |
| LB+304（A） | 按已保存默认位姿开始持续跟随，再按一次停止 |
| RB 或键盘 s | 停止跟随，保留默认位姿 |
| 键盘 x | 使用当前关系临时跟随，不覆盖保存的默认值 |
| q / Esc / Ctrl+C | 发送零增量并退出 |

先将两个标签摆成希望保持的相对姿态，等画面稳定后按 LB+305；移动目标或机械臂后按 LB+304，程序会持续修正到保存的关系。已有正确默认关系时可以直接 LB+304，重新保存会覆盖默认关系文件。达到保持状态后目标再次移动会继续跟随；要结束跟随需再按 LB+304、RB 或 s。

组合键是按下边沿触发，先按住 LB 再按 A/B，保持按住不会重复触发。默认文件为 `ros2/marker_detect/handeye_result/tag_follow_default.json`，可以用 `--default-pose` 指定其他位置。保存后重新启动会加载默认值，仍需 LB+304 才开始跟随。

标定文件必须含有效 4×4 矩阵 `X`（相机到 base_link）和 `Z`（tag10 到被控制的 TCP），平移单位米。缺少标定时只能检测、保存默认关系；原 ID 0–7 标定工具的结果不能直接替代。本入口沿用左臂 A 安装方向，接收端使用 BASE 增量、匹配的 TCP，并按 10 Hz 接收 `/omi/action/decision`。停止其他向该话题发布的策略/手柄程序，包括可能同时响应 A/B 的夹爪程序。

终端显示完整六维误差及实际发送的限幅增量，后者单位为 mm/ABC 度。`receive_age_ms` 从订阅回调收到图像时开始计时，包含解码和检测耗时；跟随不使用图像 header 计算延迟。标签丢失、检测拒绝或接收后年龄超过 120 ms 时归零暂停，重新看到有效标签后恢复；手柄断开则停止，重连后需重新启动。该年龄不包含拍摄到接收的传输时间。当前尚未实机验收跟随精度。

当前控制参数为平移/旋转增益各 0.08，每轴每周期最大 0.5 mm/0.2°。
平移误差≤2.5 mm 时平移停止，旋转误差≤0.8°时旋转停止，两部分独立处理；
停止后分别超过3.5 mm、1.2°才恢复。窗口显示 `HOLDING` 表示两部分均在保持状态、指令为零，
仍在监测目标，目标移出恢复阈值后继续跟随。重启程序后加载这些新参数。

| 窗口状态 | 操作者应如何理解 |
| --- | --- |
| `STOPPED` | 尚未启动或已手动停止，输出零增量 |
| `TRACKING` | 正在按误差修正，平移与旋转可分别归零 |
| `HOLDING` | 两部分修正均已归零，继续监测目标是否移出恢复阈值 |
| `PAUSED` | 标签或接收后时效不满足条件，暂发零增量，恢复有效观测后继续 |

<a id="tag-follow-troubleshooting"></a>

### 跟随排错

| 现象 | 检查方法 |
| --- | --- |
| `Device lacks required sticks, D-pad or RB` | 用上面的设备列表确认 Xbox 路径；不要把 SpacePilot 的 js 设备传入 |
| X/Z 缺失或 JSON 无效 | 检查 `--calibration` 指向结果文件；原始 `handeye_samples_*.json` 不能用作结果 |
| `Both tags must be visible and fresh` | 同时看清 tag10/tag12，检查标签尺寸、遮挡与当前接收后年龄，恢复有效观测后重按组合键 |
| `waiting for CameraInfo/image` | 检查驱动、图像与内参话题、ROS domain/发现配置，以及图像尺寸和光学 frame 是否匹配 |
| `PAUSED` 或接收后年龄超时 | 确认图像连续到达及本机处理耗时；`receive_age_ms` 从订阅回调起算，不是传输延迟 |
| 接近目标仍来回运动、误差反复变号 | 先按 RB/s 停止，核对启动日志是否为新参数；检查真实反馈滞后、标签稳定性和 TCP/标定配置。重启程序才会加载新参数，单纯放大死区不能证明问题已解决 |
| 发布者冲突 | 停止其他独立策略发布器；运行 RL 时使用其内置跟随 |

<a id="tag-handeye"></a>

## 首次使用：tag10 多姿态手眼标定

`tag_handeye_calibration.py` 使用与跟随程序相同的 tag10（黑框外沿 51 mm）坐标约定。
固定相机，将 tag10 刚性固定在当前受控 TCP 所在的末端；标定期间不改变相机位置、标签安装或接收端 TCP 配置。
程序只订阅彩色图、CameraInfo 和 `/tj/info/eef_left`，不创建运动指令发布器。机械臂由你用原有手动方式移动。

```bash
cd /home/zhoutong/omi_folder/omi_proj
source scripts/env_ros.sh
export ROS_DOMAIN_ID=13
local/cuda-env/bin/python ros2/marker_detect/tag_handeye_calibration.py \
  --device /dev/input/js0 \
  --output ros2/marker_detect/handeye_result.json
```

`--device` 使用上方设备列表中 Xbox 对应的路径，不能假定 js0/js1 长期不变；
使用键盘采样也可以加 `--no-gamepad`。接收端必须发布 `base_link` 坐标系下的真实 TCP 位姿。

1. 将 tag10 放在相机清晰可见的位置，停稳。
2. 点击标定窗口后按 **S/空格**，或 **LB+305**，保持约 2 秒，直到提示“样本已保存”。
3. 改变机械臂位置与朝向，重复采集 **15–25 个不同姿态**。需包含绕不同轴的旋转（例如不同方向倾斜 15–30°），不能只有平移或只绕一条轴转。
4. 按 **C / LB+304** 求解。样本覆盖、全部样本残差及三折留出验证通过后才写入目标文件；否则按提示补采或重采。
5. **D** 删除上一条，**RB** 取消当前采样，**Q/Esc** 退出。完成后退出标定窗口，重启跟随脚本或异步 RL，指定此 JSON。

每次按键后，只采集时间戳晚于按键的新图像，用 TCP 历史按相机拍摄时间配对（误差≤50 ms）。
一条样本至少包含 10 帧、跨度≥0.7 秒；检查采样期间和图像拍摄到现在的 TCP 位移≤2 mm、旋转≤0.5°，
标签波动≤4 mm/2°，标签边长≥30 px、重投影误差≤2 px。允许静止采样的图像传输延迟≤1.5秒；
标定配对继续使用 header 的拍摄时间；跟随控制另用本地订阅接收时间执行 120 ms 时效限制。

原始样本逐条保存为同目录的 `handeye_samples_日期_时间.json`。最终 JSON 包含
`X=T_base_link_camera`、`Z=T_TCP_tag10`（平移单位米）、相机内参、样本数和误差指标。
已有非空结果会先备份。单个位姿、重复姿态或质量检查失败不会生成可用于跟随的 X/Z。
结果残差是数据内部一致性指标，不等于真实定位精度验收。

当前验收门槛：平均平移残差≤3.5 mm（按用户要求从3 mm调整）、最大平移残差≤10 mm，
平均旋转残差≤1°、最大旋转残差≤3°，三折留出验证 RMS≤5 mm/2°。
每份结果 JSON 的 `quality_limits` 记录该次求解实际使用的门槛。

如果退出后需要重新求解已采集的数据，无需启动 ROS 或连接机器人：

```bash
local/cuda-env/bin/python ros2/marker_detect/tag_handeye_calibration.py \
  --solve-samples ros2/marker_detect/handeye_samples_日期_时间.json \
  --output ros2/marker_detect/handeye_result.json
```

本机当前结果已经过20条样本求解与软件校验，文件为 `ros2/marker_detect/handeye_result.json`，并非原始采样文件；平均平移残差3.03 mm、留出验证 RMS为4.22 mm/1.05°。该结果对应当时的固定安装，详见[标定来源与验证边界](../docs/archive/marker/records/marker_detect.md#tag-handeye-files)。
