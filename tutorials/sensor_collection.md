# 独立 ROS 传感器：安装、采集、录包与回放

哪些随Git获取、哪些需额外拷贝或重新安装，见[换机器清单](machine_transfer_checklist.md)。

本入口位于 `ros2/omi_sensors`，属于 OMI 自己维护的代码。外部 `daimong_ws`、
`record_data`、`diamond` 应用只作为参考，不在运行时调用。不需要 MuJoCo、Gym、Torch、
`marvin_msgs`，不会启动机械臂或夹爪控制节点。

当前默认采集 **RealSense 彩色图像 + 内参，双指触觉原图 + 预处理图 + deformation/shear**。
RealSense/触觉深度开关已实现，默认关闭、没有深度实机调试。腕部独立 gRPC 相机的新采集
驱动不属于此通用采集入口；现有独立[腕部实时测试入口](daimon_live.md)，尚未接入本页录包白名单。
旧 bag 的腕部图像仍可回放。仅传感器的 bag 不能替代包含关节反馈的完整 RL observation。

## 支持范围与尚未验证的边界

| 环境 | ROS 包目标 | 当前证据 |
| --- | --- | --- |
| Ubuntu 24.04 + Jazzy + Python 3.12 | 支持 | 本机 colcon 构建、模拟采集/录包/回放通过 |
| Ubuntu 22.04 + Humble + Python 3.10 | 支持目标，兼容代码与 CI 矩阵已提供 | 本机没有该系统，尚未运行验证 |
| 真 RealSense / 真触觉硬件 | 采集入口已实现 | 此轮没有连接设备，待现场验收 |

触觉是不可消除的厂商依赖：必须自行合法取得匹配 **Python、CPU 架构、设备固件** 的 SDK。
本机参考 SDK 包含 Python 3.12 加密模块；不能把它原样当作 Humble/Python 3.10 可用版本。
在 Humble 机器上取得 Python 3.10 SDK，并把配置 `sdk_python` 改为 `3.10`。
仅修改该字符串不会转换 SDK。不要把 Jazzy 的 rclpy 塞进 Python 3.10，反之亦然。
无 SDK 也可以运行 `plan`、`fake`、`record`、`replay`。

## 安装

先按官方文档安装对应 ROS 与 apt 软件源：
[Jazzy](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)、
[Humble](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html)。
RealSense 使用[官方 ROS wrapper](https://github.com/realsenseai/realsense-ros)，不在 OMI 重写 USB 驱动。
在干净终端，从 `omi_proj/` 执行：

```bash
# 显式允许安装系统依赖；需要 sudo，且 apt ROS 源已经配置。
bash scripts/setup_sensors.sh --install-system
# 已有依赖时，只构建：bash scripts/setup_sensors.sh
source local/sensors_ws/install/setup.bash
cp ros2/omi_sensors/config/sensors.example.json local/sensors.json
python3 -m omi_sensors.cli --config local/sensors.json plan
python3 -m omi_sensors.cli --config local/sensors.json doctor
```

也提供 `ros2 run omi_sensors omi-sensors --config ... COMMAND`。它使用构建时的系统 Python。
如果厂商依赖安装在独立虚拟环境里，应创建使用**同版本系统 Python**的
`--system-site-packages` venv，按厂商要求安装匹配依赖，激活后使用上面的 `python -m` 入口。
不要使用主项目 `.venv` 来构建/运行 Humble：主训练项目自身仍要求 Python >=3.12。

`doctor` 只检查 ROS 包、SDK 路径和声明的 Python 版本，不实例化 Sensor、不扫描 USB，
也不证明厂商二进制 ABI、网络、固件和设备兼容。缺 SDK 或驱动时返回非零是预期行为。
`setup_sensors.sh` 不自动复制 SDK、不下载未知 SDK、不写入其他项目。

## 每台机器的配置

编辑 `local/sensors.json`（本地忽略，不提交设备地址）：

- `realsense.serial`：多相机时必须指定正确序列号；留空由官方驱动选择设备。
- `color_profile`：默认 `640x480x30`，按相机支持的模式设置。
- `tactile.sdk_root`：包含 `dmrobotics/` 的目录，可用绝对路径，也可相对 JSON 所在目录。
- `tactile.host`：触觉远端设备地址；`pc_host`：设备可访问的本机网卡地址，不能用随意照抄的 IP。
- A/B 的 `port/dev_id/pc_port`：示例来自参考接口约定，不是设备探测结果；本机端口必须不同。
- A/B 的 `serial/physical_side`：现场确认后填写。元数据会标明这是配置身份，不冒充设备读取值。
- `domain_id`：默认 87。所有命令固定 localhost ROS discovery；SDK 自身仍通过网络访问设备。

同一 domain 不要同时运行 live、fake 和 replay，否则同名 topic 会混入多源数据。
监看工具的终端也要设置 `export ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1`。

## 无设备复现

```bash
# 完整验收，固定使用独立 domain 89；产物在 local/sensors-smoke-*/。
python3 scripts/check_sensors_ros.py \
  --config ros2/omi_sensors/config/sensors.example.json --output-root local

# 或用两个终端手动试：先录包，再启动模拟源。
python3 -m omi_sensors.cli --config local/sensors.json record local/sensor_demo --duration 15
python3 -m omi_sensors.cli --config local/sensors.json fake --duration 10
```

fake 不加载 SDK，也不连接相机。它生成明确标为 `synthetic-v1` 的彩色图/内参和触觉数值。
完整验收使用默认关闭深度/wrench 的配置；不把合成数据当作真实标定或性能证据。

## 现场采集和录包

确认配置、设备归属、SDK 匹配之后，由操作者执行：

```bash
# 终端 1：连接 RealSense 和双指触觉，不启动夹爪控制。
python3 -m omi_sensors.cli --config local/sensors.json live

# 终端 2：只录指定传感器；目录必须不存在，可 Ctrl+C 结束。
python3 -m omi_sensors.cli --config local/sensors.json record local/run_001
```

输出结构：`run_001/session.json`（解析后配置、平台、依赖包版本、采集代码哈希）、
`run_001/bag/`（未压缩 SQLite3 rosbag）、`run_001/recording_report.json`（各 topic 数量与缺失列表）。
元数据 topic 也明确列入录包，不靠 Image/Wrench 类型自动发现。Ctrl+C 优先给 rosbag SIGINT，
让它保存索引，超时才升级终止。突然断电/强杀不保证完整，磁盘空间需要操作者监控。
指定时长结束但有空 topic 会返回非零；Ctrl+C 的退出码可为 130，仍应检查报告。

复现采集环境时保留源码版本、`session.json`、SDK 原包及其哈希和设备固件信息。
安装脚本从 apt 安装当前可用版本，**不是不可变二进制锁定环境**；严格复现应根据归档版本
使用保留的包仓库/镜像。CI 两发行版只验证无设备路径，不证明跨发行版 bag 已现场互读。

## 回放

```bash
python3 -m omi_sensors.cli --config local/sensors.json replay local/run_001/bag
# 可选 --rate 0.5 --loop
```

回放从 bag 话题中取传感器白名单交集，不发布机械臂、夹爪控制消息。会发布 `/clock`；
需要 ROS 仿真时间的下游节点自行设置 `use_sim_time=true`。图像 header 保留原值。
同一配置默认过滤掉深度；要回放深度需显式启用对应配置。

旧 `/tj/dm_sensor/{a,b}_raw/depth/force` 与腕部相机话题兼容回放，**不会自动产生原 bag 不含的
deformation/shear**。旧包重建数值场/合并显示仍用
`bash scripts/view_observation_bag.sh BAG`（该旧工具是 Jazzy/Python 3.12 路径，不属于 Humble 便携入口）。
新包已经保存在线数值场，直接播放就能恢复当时记录的数值，不需要再次运行 SDK。

支持 SQLite3/已安装插件的 MCAP。旧 zstd 文件压缩 bag 在临时目录解压并改写临时 metadata，
不修改源 bag，退出清理临时目录；可用 `TMPDIR` 指向有足够空间的盘。
整个压缩文件会解压，需预留完整解压大小的空间。

## 数据语义与现场验收

### 性能待观察项（2026-10-02讨论）

- 看板用于流程检查与离线数据检查；在线可视化计划在另一台机器订阅topic，
  不在采集/实验机运行RViz。远程订阅仍会给采集机带来序列化及网络发送开销。
- 有界录包缓存只登记为后续观察项，当前不调整实现或缓存参数。
  真实在线采集时观察内存峰值、磁盘写入波动、帧号缺口和录包完整性；
  若出现问题，再评估缓存容量和写盘配置。topic非空不代表没有丢帧。

### 验收要求

新 topic 契约见[接口说明](../docs/agent/hardware/evolution/sensor-collection.md)。
现场至少验收：驱动版本、相机 serial/彩色尺寸/内参、A/B 物理身份、帧率与丢帧统计、
断开后的 stale/retry 状态、停止无残留进程、录包报告、回放与采集数值一致性。
默认关闭深度；以后另行验收深度单位、内参、对齐和有效值。

触觉 `host_receive_not_exposure` 时间戳不是设备曝光时间；RealSense 沿用驱动 header。
跨传感器没有硬件同步。SDK 各 getter frame ID 不一致时整帧丢弃，而不是拼成错误的“同步帧”。
厂商 baseline 目前由设备管理、无法确认可重建，明确记录 `unknown_vendor_managed`；
保存数值场能精确回放已录数值，但不能承诺仅凭原图复算完全相同的在线数值场。
