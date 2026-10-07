# SDK 原生数值看板

跨机器依赖按[转移清单](machine_transfer_checklist.md)准备；仅查看原生bag无需拷贝SDK。

这是独立的新入口，**不会修改或调用旧看板**，也不从图像重建数值场。
订阅 `/omi/tactile/{a,b}/...` 的 SDK 原生字段与 RealSense 彩色图/内参，生成供 RViz 显示的图像。
看板不需要触觉 SDK、不连接硬件、不发机器人指令，不是 RL observation 构建器。

## 立即检验（无设备）

从 `omi_proj/` 执行，系统已有 ROS Jazzy/Humble、NumPy、PyYAML、Pillow 和 RViz2：

```bash
bash scripts/view_sdk_observation.sh --fake
```

会启动模拟源、新看板和 RViz。模拟触觉明确标为 `SYNTHETIC`，相机是人工颜色渐变图；
不是实机数据。Ctrl+C 或关闭 RViz 会停止本次启动的子进程。
需要安装依赖时参照[独立采集教程](sensor_collection.md)；`setup_sensors.sh --install-system`
现在包含 `python3-pil`。源代码 Shell 入口无需先 colcon 构建，但仍需要系统 ROS/Pillow。

无桌面运行：

```bash
bash scripts/view_sdk_observation.sh --fake --no-rviz --duration 5
```

新入口默认使用 **localhost ROS domain 88**；旧稳定看板默认87，避免默认混流。
自定义 `--config FILE` 后使用配置中的domain，不再自动隔离；采集与看板配置必须一致。
domain87会打印旧看板冲突提醒。同一domain不能同时跑真实源、模拟源和回放源。

## 订阅已有采集流

```bash
# 默认只启动看板/RViz，不启动任何设备。
bash scripts/view_sdk_observation.sh --config local/sdk_sensors.json
```

`local/sdk_sensors.json` 可从 `ros2/omi_sensors/config/sdk_dashboard.example.json` 复制，
此模板domain为88。若之后要用它启动真实采集，按采集教程填写SDK路径、网络与设备信息，
在另一个终端由操作者执行采集命令。看板不会替你启动 `live`。

也可安装独立ROS包后使用：

```bash
source local/sensors_ws/install/setup.bash
ros2 run omi_sensors omi-sdk-view --config local/sdk_sensors.json
# 只发布看板、不打开RViz：
python3 -m omi_sensors.cli --config local/sdk_sensors.json dashboard
```

## 回放原生数值场 bag

```bash
bash scripts/view_sdk_observation.sh --bag local/run_001/bag --loop
# 0.5倍速，显示10Hz，接收超过1秒未更新判为STALE：
bash scripts/view_sdk_observation.sh --bag local/run_001/bag --loop \
  --rate 0.5 --display-rate 10 --stale-seconds 1
```

传入含 `metadata.yaml` 的bag目录，不是外层session目录。启动前检查启用面板需要的topic、
消息类型与非空计数；运行时继续校验schema2/来源/字段shape。
**record010旧包不含这些原生数值字段，不能直接用于新看板。** 程序会提示使用旧命令：

```bash
bash scripts/view_observation_bag.sh /home/zhoutong/omi_folder/representative_rosbag/october/record010/bag_001
```

新看板不暗中调用重建来填补缺失字段。纯触觉bag可用 `realsense.enabled=false` 的配置；
纯相机bag可关闭tactile。禁用面板显示DISABLED，不等待这些topic。

## 显示内容与状态

- 上方：RealSense原图缩略图、绿色ROI框、实际128×128预览、源时间戳、接收频率/年龄、
  同时间戳且同尺寸的CameraInfo内参。ROI为(.507,.426,.40)，预览nearest resize，**仅作显示**。
- A/B各一行：原图raw、预处理图infer、deformation箭头、shear箭头；显示shape、分量min/max、
  clipped数量、fid、配置身份、数据来源、基准状态、处理版本、SDK单位说明。
- 四个核心图与metadata精确匹配同一source stamp才更新一行；不拼接不同帧。
- `VALID`表示收到并通过结构校验的SDK样本，不代表已标定或物理正确；`SYNTHETIC`明确表示模拟。
- `WAITING`表示尚未凑齐；`STALE`表示超过接收时限；`INVALID`表示拒绝了非法输入；
  `DEVICE_WARNING`表示近期设备状态报告retrying/incomplete/stale。保留旧图时始终显示对应状态。
- depth/wrench默认关闭，不影响核心显示。启用后仅显示同stamp数据的数值摘要，缺失明确提示；
  本版没有深度热图、wrench历史曲线或腕部相机面板。

固定箭头参数：step16、2px/SDK unit、deadband0.2、显示最长24px；红色只表示显示截断，
不是力超限。向量独立绘在黑底，不假设infer图与数值场已经完成像素配准。
看板缩放不会修改原数值矩阵；人用图像不送入策略。

年龄和频率基于本机单调时钟的**接收时间**，不是设备曝光延迟或同步精度。bag暂停也会STALE；
慢速播放可增大 `--stale-seconds`。循环/后退时按metadata时间和fid检测新的数据段并清空该指旧缓存。
相机与双指各自独立，顶部明确提示没有硬件同步。身份来自SDK采集配置，不冒充设备验证结果。

输出 topic：`/omi/sdk/dashboard`（1536×1000 rgb8）、`/omi/sdk/dashboard_status`（诊断JSON）。
SDK的vendor-managed未知基准按原值显示，不替换成离线重建基准。

## 自动验收

```bash
bash scripts/setup_sensors.sh
source local/sensors_ws/install/setup.bash
python3 scripts/check_sdk_dashboard_ros.py \
  --config ros2/omi_sensors/config/sdk_dashboard.example.json --output-root local
```

脚本在domain91运行：WAITING → 模拟发布/录包 → STALE → 原生格式bag循环回放，检查
图像尺寸、匹配内参、A/B完整样本、循环重置和子进程退出，生成live.png、stale.png、report.json。
这里只是合成数据和headless验收；真实SDK数值/内参/网络表现、RViz人工操作及Humble运行仍待验证。
