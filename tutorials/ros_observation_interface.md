# 真机 ROS 观测接口（只读）

第一版接口订阅 `record010` 中的 A 臂反馈、夹爪、外部 RGB、腕部 RGB、双指触觉 raw/depth/force，按消息 header 在 10 Hz 决策时刻取最近历史样本，建立已夹取状态的触觉基线，并输出固定 shape 的 Gym/NumPy observation。接口**没有 publisher，不会发送运动命令**。

## 输出契约

| 字段 | shape | 含义 |
| --- | --- | --- |
| `state` | `(22,)` | A 臂位置/速度/力矩各 7 维，加夹爪位置 |
| `wrench_delta` | `(12,)` | 双指六轴力相对抓取基线的变化 |
| `external_rgb` | `(128,128,3)` | 头部相机 ROI RGB |
| `external_rgb_roi_offset_px` | `(2,)` | 头部 ROI 中心相对原图中心的 `[dx,dy]` 像素偏移；`+x` 向右、`+y` 向下 |
| `wrist_rgb` | `(128,128,3)` | 腕部/夹爪 RGB |
| `tactile_raw` | `(64,64,2)` | 双指灰度触觉图 |
| `tactile_depth_delta` | `(64,64,2)` | 双指触觉深度相对抓取基线的变化 |
| `sensor_age_s` | `(10,)` | 各传感器在决策时刻的样本年龄 |
| `sensor_valid` | `(10,)` | 新鲜度掩码；默认要求全部有效 |

`observation_to_torch()` 会添加 batch 维，把 HWC 图像转成 BCHW，并把 `uint8` 归一化到 `[0,1]`。策略代码也可直接调用 `TianjiRosObservationNode.latest_torch_observation()`。

两路 RGB 都先裁剪正方形 ROI，再缩放到 `128×128`。`record010` 的头部原图为
`640×480`，当前 ROI 是左上角 `(228,108)`、大小 `192×192`，所以
`external_rgb_roi_offset_px=[4,-36]`。该字段逐 observation 保存；未来 ROI 随交互物体
移动时，图像和偏移量能够保持对应。可通过
`builder.set_external_rgb_roi_center(center_x, center_y)` 更新归一化中心坐标，ROI 大小保持不变。
完整图像链为 `640×480 → 裁剪 192×192 → resize 128×128`，resize 后边长约为
裁剪框的 `66.7%`。

Wrist 原图为 `1920×1080`，ROI 固定为 `389×389`：横向居中，左上角
`(766,566)`，范围 `x=[766,1155)`、`y=[566,955)`。纵向位置沿用当前设置。
完整图像链为 `1920×1080 → 裁剪 389×389 → resize 128×128`，resize 后边长约为
裁剪框的 `32.9%`。Wrist ROI 不产生额外偏移字段，也不作为策略参数传输。

## 离线验证 record010

需要 ROS 2 Jazzy、MCAP 插件及已构建的 `marvin_msgs`。当前机器可这样配置自定义消息路径：

```bash
export OMI_MARVIN_MSGS_SETUP=/home/zhoutong/Downloads/img/record001/bag_001_jazzy_tools/install/setup.bash
source scripts/env_ros.sh
python -m omi_hil_rl.real.ros_bag_preflight \
  /home/zhoutong/Downloads/img/record010/bag_001
```

本次实际验证在 10 Hz 下得到 269 个 observation，0 个因缺失或过期被拒绝。腕部 RGB 是最慢的必要输入，实测最大年龄约 0.225 秒，因此默认 stale 阈值暂定为 0.25 秒。该数值只描述这份 bag，不是最终在线控制参数。

## 从无接触窗口提取触觉基准

`record010` 在 `25.0–26.0 s` 持续完全张开。该结论同时有外部相机、夹爪位置、双侧 depth
和 wrench 证据。以下命令只读 bag，在被 Git 忽略的 `local/` 新建基准目录：

```bash
source scripts/env_ros.sh
python -m omi_hil_rl.real.tactile_baseline \
  /home/zhoutong/Downloads/img/record010/bag_001 \
  local/tactile/record010_zero_load_25_26_confirmed_v2 \
  --start-s 25 --end-s 26 \
  --serial-a X26040546 --physical-side-a right \
  --serial-b X26040345 --physical-side-b left
```

预期输出包含双指 NPY/PNG 基准、合并 NPZ、五帧张开画面和 `metadata.json`。命令拒绝覆盖
已有目录；需要重做时使用新的输出目录，保留旧结果用于对照。成功报告应显示 A/B raw
分别约 24/23 帧、shape `270×360` 且 `zero_load_validation.all_passed=true`。

当前 bag 没有记录厂商 serial；操作者已在 bag 外确认 A 为右侧 `X26040546`、B 为左侧
`X26040345`，上面的参数会把这组映射写入基准包。deformation/shear 的底层离线重建本身
不需要 serial。

## 离线重建 deformation 和 shear

以下命令使用隔离环境和 Daimon CPU 底层算法，只读 bag，不构造 `Sensor`：

```bash
source /opt/ros/jazzy/setup.bash
PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}" \
  local/venvs/daimon312/bin/python -m omi_hil_rl.real.tactile_offline \
  /home/zhoutong/Downloads/img/record010/bag_001 \
  local/tactile/record010_zero_load_25_26_confirmed_v2 \
  local/tactile/record010_offline_fields_confirmed_v3 \
  --sdk-root ../diamond/daimon_stuff/dm_gripper_tac_py
```

默认输出 23、25.5、28 秒的双指 NPZ、deformation/shear PNG、双行 dashboard 和 JSON。
25.5 秒应为零或接近零；23/28 秒应出现结构化接触场。重建 depth 与记录 depth 的空间
形状高度相关但幅值不同，不能用重建值覆盖 bag 原值。

## 在线只读检查

确认对象已经夹住且机器人保持静止后运行：

```bash
export OMI_MARVIN_MSGS_SETUP=/path/to/marvin_msgs/install/setup.bash
source scripts/env_ros.sh
python -m omi_hil_rl.real.ros_observation_live --torch
```

命令先等待全部 topic，再经过 1 秒 warmup，以最近 0.5 秒触觉数据的平均值保存抓取基线，之后周期输出样本年龄、有效标记和网络张量 shape。`Ctrl+C` 退出。自动基线仅用于接口验证；正式 episode reset 应在操作者或状态机确认“已夹取、未接触插口”之后显式调用 `capture_grasp_baseline()`。

## 离线 ROI/RViz 可视化

以下命令从 `omi_proj/` 执行，只回放两路相机 topic，不会回放 bag 中的机械臂控制 topic：

```bash
BAG=/path/to/record010/bag_001

# 保留的最初单进程版本：原图 + 128×128 ROI，通常最流畅
../ros2_camera_clip_tools/view_camera_clip_original.sh "$BAG" 1.0

# 多模式入口：第三个参数可为 observation、512 或 both
../ros2_camera_clip_tools/view_camera_clip.sh "$BAG" 1.0 observation
../ros2_camera_clip_tools/view_camera_clip.sh "$BAG" 1.0 512
../ros2_camera_clip_tools/view_camera_clip.sh "$BAG" 1.0 both
```

`both` 使用两个图像处理进程：第一进程发布 128 clip 和第一版 dashboard，第二进程订阅
128 clip 后放大并发布第二版 dashboard；RViz 只负责显示。两个大型 raw Image 同时渲染会
增加负载。Wrist 原始频率约 10 Hz，因此即使没有积压也会呈现约 10 FPS。关闭 RViz 或
`Ctrl+C` 停止。可视化使用 `--loop`，bag 播完后会从头重复。

512 图只用于人工检查，策略 observation 仍为 128。可视化工具与 observation 使用相同
ROI 边界，但前者以 Lanczos 生成 128 clip，后者当前使用最近邻，不能把 RViz 像素直接当作
策略实际输入的逐像素证据。

## 边界

- 当前没有 TCP/FK、动作空间、IK、安全投影、命令插值、reward、episode 或成功判定。
- 不要用 `ros2 bag play` 将记录中的 `/tj/control/joint_cmd_A` 回放到真实控制域。
- 真机动作发布必须放在独立、显式授权并经过现场验收的安全执行层，不能直接加入此订阅节点。
