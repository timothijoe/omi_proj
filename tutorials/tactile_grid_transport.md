# 触觉24×16低带宽发布（可选第一版）

配套：[常用命令速查](sensor_commands.md) · [腕部相机专项](wrist_camera.md)。
三个文件共同维护：变更开关、默认参数、topic时同步核对；本页负责触觉详细语义和录包检查。

## 当前推荐命令：raw和wrench显式开启

```bash
# 默认：仅deformation、shear、depth及metadata/status
bash scripts/start_daimon_live.sh tactile --transport network
# 额外发送原始触觉图像
bash scripts/start_daimon_live.sh tactile --transport network --publish-raw
# 额外发送六维力/力矩
bash scripts/start_daimon_live.sh tactile --transport network --tactile-wrench
# 两者都要（可先加 --plan 检查）
bash scripts/start_daimon_live.sh tactile --transport network --publish-raw --tactile-wrench
```

停止旧触觉进程后重启才生效，不影响独立腕部进程。raw为SDK原尺寸mono8，不缩放不压缩，
沿用`/omi/tactile/{a,b}/raw`；数值场仍为`/omi/tactile_grid24x16/{a,b}/...`。
infer仍不发。wrench无SDK帧号时明确标记未同步，需连同metadata录制。
旧full模式仍保留raw/infer默认，兼容旧看板；以上显式raw开关针对grid模式。
通用grid回放器当前尚不订阅新增raw，发出/录入不等于看板已经显示。

前提：已按[戴蒙实时教程](daimon_live.md)准备SDK、Python环境和网络。
本页24×16指**宽24、高16**；NumPy矩阵为16×24×2。只采集，不控制机器人。

## 原始触觉与小矩阵：命令对照

以下从项目根目录执行，均使用 domain13、允许跨电脑发现。**两种模式选一种；
切换前先在旧触觉终端按 Ctrl+C，不能同时占用同一套触觉设备。**

### 原始触觉：完整矩阵

```bash
export ROS_DOMAIN_ID=13
bash scripts/start_daimon_live.sh tactile --transport network --tactile-mode full
```

### 小矩阵触觉：区域平均后的矩阵

当前`tactile`默认即小矩阵并开启depth；wrench与raw显式开启，也可显式指定模式：

```bash
export ROS_DOMAIN_ID=13
bash scripts/start_daimon_live.sh tactile --tactile-mode grid24x16 --transport network
```

| 项目 | 原始触觉 | 小矩阵触觉 |
|---|---|---|
| 每个场的形状（高×宽×通道） | 288×384×2 | 16×24×2 |
| a指 deformation | `/omi/tactile/a/deformation` | `/omi/tactile_grid24x16/a/deformation` |
| a指 shear | `/omi/tactile/a/shear` | `/omi/tactile_grid24x16/a/shear` |
| 消息类型 | `sensor_msgs/msg/Image` | `sensor_msgs/msg/Image` |
| 数值编码 | `32FC2` | `32FC2` |
| 单个场数值载荷 | 884736字节 | 3072字节 |

b指将话题路径中的 `/a/` 换成 `/b/`。这里的 Image 装的是两个通道的浮点数值场，
不是用于观看的RGB图片。小矩阵将每18行×16列取平均，不缩放向量幅值。
小矩阵默认不提供raw/infer；raw可显式开启，也不能直接接旧触觉看板或替换策略输入。

只在同机使用时，去掉 `--transport network` 即可。
域优先级为 `--domain` > `ROS_DOMAIN_ID` > 默认88；更改后重启相关节点。
network模式开放发现，但跨机器/Humble接收效果仍需现场验证。

## 启动与恢复

在项目根目录，先检查计划（不打开传感器）：

```bash
bash scripts/start_daimon_tactile_grid.sh --plan
```

停止原来占用双指触觉的终端（Ctrl+C），再启动新模式：

```bash
bash scripts/start_daimon_tactile_grid.sh
# 等价入口
# bash scripts/start_daimon_live.sh tactile --tactile-mode grid24x16
```

不要同时启动两套触觉SDK。新旧入口共用触觉占用锁，但无法检测所有外部SDK程序。
Ctrl+C停止；恢复旧版只需：

```bash
bash scripts/start_daimon_live.sh tactile --tactile-mode full
```

`tactile`不指定模式默认grid24x16；`all/view`仍默认full以保留旧看板。旧回放和相机入口不变。
**新模式默认不提供raw/infer，不接旧触觉看板**；`all/view --tactile-mode grid24x16`会拒绝启动，
请勿将小矩阵重映射到旧话题冒充全分辨率。

## 检查消息

以下对应上面的 domain13 网络模式，在接收机器已加载ROS环境的终端执行：

```bash
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
ros2 daemon stop
ros2 topic echo --once --no-arr --qos-reliability best_effort /omi/tactile_grid24x16/a/deformation
ros2 topic echo --once /omi/tactile_grid24x16/a/metadata
```

若采用同机默认启动方式，接收端需改用实际domain，并设置
`ROS_LOCALHOST_ONLY=1`、`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`。

预期Image：`height: 16`、`width: 24`、`encoding: 32FC2`、`step: 192`；每场数据3072字节。
两指分别为a、b，各有deformation、shear、depth、metadata、status。metadata记录网格模式、
原尺寸、处理方法/版本、SDK帧号、原接收时间戳和单位。数值不是JSON/String；只有元数据/状态是String。

原录包脚本白名单尚不包含新话题。需要保存时可以显式录制（输出目录必须不存在）：

```bash
ros2 bag record --storage sqlite3 -o local/tactile_grid_trial \
  /omi/tactile_grid24x16/a/deformation /omi/tactile_grid24x16/a/shear \
  /omi/tactile_grid24x16/a/depth \
  /omi/tactile_grid24x16/a/metadata /omi/tactile_grid24x16/a/status \
  /omi/tactile_grid24x16/b/deformation /omi/tactile_grid24x16/b/shear \
  /omi/tactile_grid24x16/b/depth \
  /omi/tactile_grid24x16/b/metadata /omi/tactile_grid24x16/b/status
```

这是仅触觉网格的测试录包，不是完整模仿学习数据集；相机、关节/TCP等需另行纳入。
旧白名单回放入口不会播放这些新话题；可用`ros2 bag play local/tactile_grid_trial`。
策略自动订阅适配未实现，不能直接换掉现有训练数据源。

## 收益与边界

SDK完整场288×384×2先按18行×16列区域平均，再以float32发布；不缩放向量幅值。
双指两个场合计30Hz，理论数值载荷106.17 MB/s降至0.369 MB/s（1/288），不含协议与元数据。
此模式默认不发送raw/infer；默认开启深度，raw/wrench显式开启，深度区域平均，wrench保持原值。
含深度的双指五通道30Hz净载荷为0.4608 MB/s，另加少量wrench与元数据。
开启可选数据后，录包列表还需加入`/omi/tactile_grid24x16/a/wrench`、
`/omi/tactile_grid24x16/b/wrench`和/或`/omi/tactile/a/raw`、`/omi/tactile/b/raw`。

处理发生在**采集主机SDK之后、ROS发布之前**，不减少传感器到主机的SDK流量，
也没有承诺CPU/内存降低288倍。默认仍限制本机发现，远端订阅使用上述network模式并匹配接收端配置。
区域平均不可逆，会抵消反向向量、弱化小接触，建议保留一些完整场对照数据。

验证：数值/入口自动测试、Jazzy双进程合成发布订阅通过；最新实录包的三场和depth已可视化，
历史包wrench无消息的SDK适配问题已修复，六维力本地真机出流通过；无SDK帧号时仍明确标记未同步。
raw开关通过合成ROS测试，本轮组合真机尚未验收；时钟偏差、长期30Hz、Humble及训练效果仍待验证。

## 看不到raw时怎么判断

未加`--publish-raw`时grid模式**不创建raw/infer发布者**，这不是接收端topic名称错误。
不要尝试改订`/omi/tactile_grid24x16/a/raw`来解决，它目前并不存在。
full模式的raw仍使用`/omi/tactile/{a,b}/raw`。不含raw的旧包无法靠RViz补出原图。
“小矩阵加可选raw”现已实现`--publish-raw`，详见本页开头；旧包缺失的原图无法补回。
发布开关开启也不等于录制成功：尤其wrench必须检查非零消息数与metadata状态。
