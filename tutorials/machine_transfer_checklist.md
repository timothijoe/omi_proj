# 换机器：额外拷贝与重新安装清单

**Git只带代码、配置模板、文档和校验清单，不带厂商SDK、bag、基准、模型和虚拟环境。**
先选择要运行的功能，再准备对应资源；不要把全部参考工程或旧机器的venv/install一起搬过去。

## 1. 按用途准备

| 要做什么 | Git之外必须另外准备 | 不需要拷贝 |
| --- | --- | --- |
| 新SDK看板 `--fake` | 无数据/厂商包；安装ROS、Pillow等系统依赖 | SDK、基准、bag、机器人模型、marvin_msgs |
| 新SDK看板播放原生bag | 完整原生字段bag；建议同时保留session.json和recording_report.json | SDK、离线基准、仿真模型 |
| 新SDK看板订阅已运行采集 | 匹配的本机配置（topic使用固定名称，domain须一致） | 看板进程本身无需SDK |
| 本机启动真实触觉采集 | 匹配Python/架构/固件的Daimon SDK、厂商依赖和本机设备配置 | 离线record010基准不是SDK直读的必需品 |
| 旧稳定看板播放record010 | 完整bag、Daimon SDK、原A/B基准；重建Python环境 | 整个diamond/daimong_ws/record_data工程、marvin_msgs |
| 迁移版看板/CPU重建 | 同上，但SDK默认放项目local/vendor下 | 外部diamond工程 |
| 比对迁移前后数值 | 再加六个历史参考NPZ，保留相同基准metadata | 重放缓存、生成PNG不是数值回归的必需品 |
| 旧完整ROS observation/关节反馈 | 上述观测所需数据，以及匹配的marvin_msgs源码并重新构建 | 新SDK纯传感器看板不需要此包 |
| 新外部录包原生字段+3D看板 | 原包ZIP/目录、匹配marvin_msgs源码重建、robot_assets及相邻MarvinCCS；安装Jazzy/RViz/robot_state_publisher、NumPy/Pillow/SciPy/PyYAML/zstd | 触觉SDK、零载荷基准、机械臂SDK；缓存和URDF可再生成 |
| Stand方向修正版回放（当前对照推荐） | 原包ZIP/目录、匹配marvin_msgs源码重建、原Stand RAR；ROS/Jazzy、RViz、robot_state_publisher、项目Python环境、NumPy/Pillow/SciPy/PyYAML/zstd、系统libarchive | 旧MJCF/MarvinCCS、触觉SDK、机械臂SDK；无需复制运行临时URDF |
| 保留命名派生模型 | 整个 `local/models/omi_marvin_stand_axis_corrected_v1/`，含URDF、meshes、source、README、provenance | 不需要整个SolidWorks工程；此归档不是现有回放脚本的直接输入 |
| Hybrid新外观＋旧链对照 | Stand回放依赖，加上旧robot_assets/MarvinCCS；额外做外观配准 | 触觉SDK、机械臂SDK |
| MuJoCo真实模型仿真 | robot_assets与相邻MarvinCCS完整资源树 | 厂商触觉SDK不是仿真必需品 |
| 未来臂SDK操作 | Tianji SDK_PYTHON及原生库、工具/控制器配置，另行安全验收 | 仅看图不需要机械臂SDK |

旧record010没有新SDK看板所需的完整原生字段，不能因为“都叫bag”就互换入口。
外部新包的 `/tj/dm_sensor/` 数值topic也不是schema2 SDK看板格式；使用
`view_recorded_observation_3d.sh`（旧模型）或当前[Stand方向修正版](corrected_stand_review.md)
（另需原Stand RAR），见[3D操作教程](robot_3d_replay.md)。
在目标机填写 `local/robot_state/viewer.env`（模板 `scripts/robot_viewer.env.example`），
配置本机重建的Marvin overlay；可用 `OMI_TACTILE_PYTHON` 指向满足依赖的ROS Python环境。
只拷贝相机标定图片或渲染截图也不能替代bag和数值参考样本。

## 2. 当前机器可以作为拷贝来源的资源

下面的绝对路径仅用于找到**这台机器**的源，不要求另一台机器保留相同用户名或Downloads布局。
厂商包只在有使用/迁移许可的目标环境间转移；未确认公开再分发权，不进入Git。

| 资源 | 当前来源 | 建议目标 | 当前约大小 |
| --- | --- | --- | --- |
| Daimon完整本地归档 | `omi_proj/local/vendor/daimon_tactile/` | 新机器 `omi_proj/local/vendor/daimon_tactile/` | 358 MiB |
| record010零载荷基准 | `omi_proj/local/tactile/record010_zero_load_25_26_confirmed_v2/` | 同项目相对路径 | 1.2 MiB |
| 六组历史参考及图片 | `omi_proj/local/tactile/record010_offline_fields_confirmed_v3/` | 同项目相对路径；回归至少保留6个NPZ | 完整目录13 MiB |
| record010原始bag | `/home/zhoutong/Downloads/img/record010/bag_001/` | 自选数据盘，例如 `omi_proj/local/bags/record010/bag_001/` | 5.3 GiB |
| marvin_msgs源码 | `/home/zhoutong/Downloads/img/record001/bag_001_jazzy_tools/src/marvin_msgs/` | 新ROS工作区的 `src/marvin_msgs/` | 按需 |
| 机器人模型 | `omi_proj/local/assets/robot_assets/`、`omi_proj/local/assets/MarvinCCS/` | 两目录保持相邻，连同provenance.json保留 | 按需 |
| Stand原始归档 | 用户提供的 `Marvin_Stand_2026.2.2.rar` | 自选本地资源目录，命令显式传入 | 按需 |
| OMI方向修正版模型 | `omi_proj/local/models/omi_marvin_stand_axis_corrected_v1/` | 同项目相对路径，整个目录 | 含15个STL，不随Git迁移 |
| 臂SDK | 工作区同级 `TJ_FX_ROBOT_CONTRL_SDK/` | 自选目录，包含完整SDK_PYTHON及原生库 | 按需 |

SDK必须复制完整运行归档，不能只拷贝 `dmSDK.py`：`dmrobotics/`中的模型/库、`Daimon/`运行时
和 `migration-manifest.json` 都需要保留。归档后校验：

```bash
# 从omi_proj根目录执行，只校验，不加载SDK或连接设备。
export PYTHONPATH="$PWD/ros2/omi_sensors${PYTHONPATH:+:$PYTHONPATH}"
python3 -m omi_sensors.vendor_bundle verify local/vendor/daimon_tactile
```

如果拿到的是新的厂商发行包而不是这份归档，按[迁移教程](tactile_reconstruction_migration.md)
执行 `vendor_bundle import` 创建新目录和manifest。哈希不同表示版本/资源不同，不能直接宣称复现同一算法。

bag要保留 `metadata.yaml` 及其引用的**全部** `.mcap/.db3/.zstd` 分卷；不要只拷第一卷。
新采集session建议整目录复制，包含配置/依赖版本记录。基准的metadata参与baseline_id哈希，
复制时保留内容，不要为了调整路径就随意重写它；运行路径通过CLI参数指定。

## 3. 应安装/重建，不直接复制的包

- **ROS Jazzy或Humble、rclpy、标准消息、rosbag存储插件、RViz、RealSense驱动**：在目标系统安装。
  现有安装脚本列出包名，不会复制 `/opt/ros`。SDK原生看板本身不要求安装RealSense驱动，
  只有真实相机采集才需要；综合安装脚本为采集用途仍会安装它。
- **NumPy/PyYAML/Pillow等Python依赖**：目标机安装；需要触觉SDK时再按厂商发行版本准备依赖。
- **`.venv/`、`local/venvs/`**：重新创建，不跨机器复制。它们包含解释器路径和本机二进制依赖。
- **`local/sensors_ws/{build,install,log}`**：在目标机运行 `bash scripts/setup_sensors.sh` 重新构建。
- **marvin_msgs**：只搬匹配的源码，再在目标ROS下colcon构建；不要搬旧Python3.12的生成消息给Humble。
  其定义必须和真实生产者/录包一致，尤其旧接口使用的 `Jointfeedback.arm_positions/arm_velocities/arm_efforts`。
- **pip缓存、replay_cache、预览PNG、临时诊断日志**：通常可以重新生成；保留重要验收报告作为证据，
  但它们不能替代源数据。回放缓存重建需要足够的临时解压空间。

### Python/SDK兼容性特别说明

Jazzy/Ubuntu24.04使用Python3.12；Humble/Ubuntu22.04通常使用Python3.10。
当前算法载荷验证在Python3.12上通过；即使 `Daimon/` 目录中有py310运行时，也不能据此
认为每个加密算法文件和原生模型库都支持Python3.10。Humble必须取得匹配SDK并另行验证。

当前 `local/venvs/daimon312` 离线重建环境可见版本为 NumPy1.26.4、h5py3.16.0、
Gymnasium1.3.0、Pillow10.2.0、SciPy1.11.4，cv2来自Ubuntu系统包。
**这只是已验证环境的记录，不是可保证在线Flux运行的完整依赖锁。**
本轮检查该环境未发现可导入的grpc、onnxruntime、pyudev；SDK setup还声明了grpcio/protobuf/
cryptography/OpenCV/ORT等依赖，需按厂商CPU/Flux指引另行安装与验收。
不能把“补h5py和gym就能做离线重建”写成“在线采集全部依赖已经齐全”。
不要在不确认用途的情况下照搬GPU依赖或为CPU看板安装CUDA。

## 4. 旧稳定入口换机器怎么保持不改代码

先恢复bag/基准/SDK，准备Python3.12环境和Jazzy。旧脚本仍默认寻找同级diamond SDK，
可以用**已有环境变量**覆盖到项目本地归档，无需修改稳定脚本：

```bash
export OMI_DAIMON_SDK_ROOT="$PWD/local/vendor/daimon_tactile"
export OMI_TACTILE_BASELINE="$PWD/local/tactile/record010_zero_load_25_26_confirmed_v2"
export OMI_TACTILE_PYTHON="$PWD/local/venvs/daimon312/bin/python"
bash scripts/view_observation_bag.sh /YOUR_DATA_DISK/record010/bag_001
```

这里假设已经在目标机**重建**这个venv，而不是从旧机器拷贝。迁移版 `_migrated.sh`
默认SDK已是local/vendor，不必复制整个diamond参考应用。

## 5. 本机配置需要重填，不要盲拷

以Git中的 `sdk_dashboard.example.json`（domain88）或 `sensors.example.json`（domain87）
创建目标机local配置；重填SDK路径、RealSense serial、触觉host/pc_host/端口与dev_id，核对A/B物理身份。
配置相对路径按JSON所在目录解析：若配置在 `local/sdk_sensors.json`，SDK写
`vendor/daimon_tactile`，不是再次写 `local/vendor/daimon_tactile`。
`pc_host`必须是设备能访问的新机器网卡地址，不能照抄旧IP。图像分辨率/标定、ROS domain也需核对。

恢复旧机器人观测时，source目标机重建的marvin_msgs overlay；主项目的
`scripts/env_ros.sh` 支持 `OMI_MARVIN_MSGS_SETUP=/YOUR_WS/install/setup.bash`。
这是消息依赖，不提供关节反馈生产者；要取得真实反馈还需现场已有的机器人ROS节点，OMI采集包未集成它。

无需整体复制 `daimong_ws`、`record_data`、`ros2_camera_clip_tools` 或 `cooking_proj`：
它们是参考或历史独立工具。当前OMI自带看板/录包逻辑；需要的是上表明确列出的SDK、数据或资产。
若要继续使用某个历史外部工具，它才是该特定入口的额外依赖。

## 6. 转移后验证顺序

1. 先运行 `view_sdk_observation.sh --fake`：不依赖SDK/原始数据，检查ROS和GUI环境。
2. 校验SDK bundle；有历史基准/NPZ时运行重建回归，核对资源指纹。
3. 新SDK bag用新入口，record010用旧稳定入口；不要混用。
4. 运行 `plan/doctor` 检查本机配置；doctor不检查全部厂商二进制和依赖，不等于设备已验收。
5. 经操作者确认后再启动真实采集，核验身份/频率/错误状态/记录完整性；不自动启动机械臂动作。

仅恢复采集/可视化不意味着真机RL闭环完成，剩余接口见[ROS到策略方案](../docs/design/ros-to-policy-integration.md)。
