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
source scripts/env_marvin.sh  # 项目 local/ 下的消息包，详见 marvin_messages.md
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

## 同时查看相机与触觉

从 `omi_proj/` 执行：

```bash
bash scripts/view_observation_bag.sh /home/zhoutong/Downloads/img/record010/bag_001
```

同一个 RViz Image 显示两部分：左侧上下分别是头部和腕部相机，每行有带 ROI 框的原图
预览和实际 `128×128` 裁剪图；右侧上下分别是 A/B 的 raw、deformation、shear。
合成图为 `1792×740 rgb8`。原图缩放适配面板，小裁剪图在合成图中占 128×128 像素；
RViz 窗口缩放时可能整体缩放。

四路传感器共用一个播放器，所以进度、倍速和循环一致。传感器本身异步采样，触觉计算
也有延迟；这不是同时间戳的跨传感器配准。每块面板显示自己的源时间戳、接收年龄和
WAITING/VALID/STALE。界面沿用原相机工具的 Lanczos 裁剪缩放，策略 observation 仍使用
原有最近邻处理。

首次生成独立的四路传感器缓存，旧的纯触觉缓存保留；不会把控制 topic 放入缓存或回放。
先关闭此前的纯触觉回放，避免同一 domain 内有两个播放器。`Ctrl+C` 或关闭 RViz 结束。

```bash
# 半速查看
bash scripts/view_observation_bag.sh /path/to/bag 0.5
# 无 GUI 检查
bash scripts/view_observation_bag.sh /path/to/bag 1.0 --no-rviz
```

环境变量与下面纯触觉入口相同。显示 topic 为 `/omi/observation/dashboard`，使用 Reliable
QoS；默认 localhost domain 87。依然可以单独运行下面的纯触觉版本。

## 播放时实时查看触觉向量

从 `omi_proj/` 执行：

```bash
bash scripts/view_tactile_bag.sh /home/zhoutong/Downloads/img/record010/bag_001
```

打开独立 RViz，顶部为 A（右指），底部为 B（左指），每行从左到右为 raw、deformation、
shear。箭头固定比例显示，红色表示超出显示长度；单位未标定，不能解释为牛顿。
`Ctrl+C` 或关闭 RViz 会停止此入口启动的进程，不关闭已有相机窗口。

首次启动先生成约 110 MB 的双指 raw 缓存，需暂存整份解压 MCAP；以后直接复用缓存。
不会在源 bag 目录里解压，因此可以和现有相机播放器同时运行。两个窗口的播放进度独立。
触觉默认使用 localhost ROS domain 87，只播放双指 raw，不播放动作 topic。

```bash
# 半速播放；计算和显示默认目标仍为 10 Hz
bash scripts/view_tactile_bag.sh /path/to/bag 0.5
# 无界面验证，只启动回放、数值计算和 dashboard publisher
bash scripts/view_tactile_bag.sh /path/to/bag 1.0 --no-rviz
```

可用环境变量指定 `OMI_TACTILE_BASELINE`、`OMI_DAIMON_SDK_ROOT`、`OMI_TACTILE_PYTHON`、
`OMI_TACTILE_RATE` 和 `OMI_TACTILE_ROS_DOMAIN_ID`。默认沿用本机已确认的 record010
基准、Daimon 隔离环境及同级 SDK。换传感器或录制时必须选择对应基准，不能沿用错误身份。

`WAITING` 表示尚未收到同侧同时间戳的完整样本；`STALE` 表示超过 0.5 秒没有完整新样本。
处理慢时会跳旧帧；播放循环间的等待也会显示 STALE。源时间戳保留历史 bag 时间，
显示年龄按本机收到完整样本后的经过时间计算。

数值 topic 为 `/omi/tactile/{a,b}/{deformation,shear}`（`32FC2`），显示 topic 为
`/omi/tactile/dashboard`（`rgb8`）。手动打开 RViz 时须使用同一域号、Image 显示、
Reliable QoS。这个版本仅显示 raw 和向量场，不含完整 depth/wrench 验收面板。

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
