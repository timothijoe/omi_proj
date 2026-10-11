# RealSense AprilTag marker 检测与位姿记录

从仓库根目录 `omi_proj/` 执行以下命令。脚本订阅 ROS 2 RealSense 彩色图像和内参，求出两组 marker 各自相对于**彩色相机光学中心**的位姿。SSH 无桌面时使用 `--headless`，不需要 X11 转发。算法、单位和验证范围见[技术说明](../docs/marker_detect.md)。

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
