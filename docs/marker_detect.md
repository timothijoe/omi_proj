# AprilTag marker 相机位姿与手眼标定

实现脚本：[hand_eye_calibration.py](../ros2/marker_detect/hand_eye_calibration.py)。运行步骤见[marker 检测教程](../tutorials/marker_detect.md)，手眼方程推导见[原理说明](../ros2/marker_detect/hand_eye_calibration_principle.md)。

## 数据流与坐标

脚本订阅 RealSense ROS 2 彩色图像 `/camera/camera/color/image_raw` 和对应的 `/camera/camera/color/camera_info`。彩色 `CameraInfo.k`、`d` 用于 AprilTag 角点的 PnP 解算；默认还订阅 `/camera/camera/aligned_depth_to_color/image_raw`，仅把与彩色帧时间相差不超过 100 ms、尺寸相同的深度用于显示和保存参考值。没有深度图仍可解算位姿。深度值不参与 PnP 或手眼求解，也不会作为采样拒绝条件。

板参数固定在脚本的 `BOARDS` 中：45 mm 外框使用 tag ID 0–3，50 mm 外框使用 ID 4–7；两组的 tag 位图边长均为 20 mm。每组至少检测到 2 个 tag 才进行 PnP。打印应使用仓库内的 [A4 标记板](../ros2/marker_detect/apriltag_45_50mm_A4.pdf)，保持 100% 比例并贴平；打印缩放会直接造成平移尺度错误。A4 文件重复印了三行相同 ID，检测器按图像位置把每行分开，优先选取标签数较多且靠近画面中心的那组，并检查重投影误差不超过 5 px。当前 PDF 的 tag 图案与 OpenCV 字典生成方向相差 180°，程序会尝试两种角点对应并选择误差较小的位姿。

每组单独输出 `T_cam_board`：它把该组 marker 中心坐标系中的点变换到**彩色相机光学坐标系**。板中心为原点，从板正面看 `+x` 向右、`+y` 向上、`+z` 垂直板面朝外。`T_cam_board[:3, 3]` 的单位是米，程序显示和 JSON 的 `translation_mm` 用毫米；`rpy_deg` 为 ZYX 欧拉角，单位度。`dist_to_optical_center_mm` 是平移向量的欧氏长度，不是仅沿光轴的 Z 深度。JSON 的 `camera_frame` 取自彩色 `CameraInfo.header.frame_id`。

## 两种运行方式

- `--cam-only`：只计算 marker 相机位姿；图像窗口中按 `s` 对连续帧取中值平移、平均旋转后写入 `handeye_result/cam_only_samples.json`。按 `d` 删除本次运行的上一条，按 `c` 查看汇总。
- `--cam-only --headless`：适合 SSH。完全不调用 OpenCV 窗口，每秒输出检测到的 XYZ、RPY、光学中心距离、tag 数和重投影误差；默认每 2 秒自动采一组并追加保存。`--capture-interval` 改间隔，`--max-samples` 限制本次样本数，Ctrl+C 正常退出。没有可用显示服务时，`--cam-only` 也会自动进入此模式；SSH 中建议显式传入 `--headless`。

需要 eye-to-hand 外参时，图形模式中使用 `--ros2` 读取机器人 `base_link <- tool0` TF，采集多组末端位姿与 `T_cam_board`，按 `c` 求 `T_base_cam`。`--manual` 和 `--ros1` 只改变末端位姿来源，**相机图像仍必须来自 ROS 2 话题**。当前无界面模式仅支持 `--cam-only`；手眼标定采样仍需要窗口操作。

## 验证边界

已用合成 AprilTag 图像验证角点检测、PnP 平移方向与米/毫米转换；用构造的 ROS 消息验证彩色内参、图像与对齐深度解码；用模拟相机验证无窗口自动采样和 JSON 保存。尚未在本机用真实 RealSense 与机械臂实测位姿精度或手眼外参。
