# 图像重建接口迁移：当前方案

## 迁移边界

将 OMI 原有 `tactile_live.FieldProcessor` 提取为独立包的
`omi_sensors.reconstruction.FieldProcessor`，供新迁移版可视化调用，也可无 ROS 单独使用。
原稳定入口保留旧实现，不依赖新共享类；迁移版必须显式选择。
它是 **OMI 维护的适配器 + 厂商算法**，不是自主实现的光流/剪切算法。
SDK 的 `dmSDK.py` 与相关算法是 PyArmor 加密实现；没有解密、反编译、修改算法。
参考目录未找到明确再分发许可，不由此推断获得公开分发权。

## 两种来源

- `image_reconstruction`：当前接口输入为 `legacy_infer_mono8` 与固定基准，输出
  deformation/shear `H×W×2 float32`。调用 CPU FlowTracker + Decomposer。
- `sdk_direct`：采集进程从 SDK getter 取数值场；格式同为 32FC2，并保留自身来源/基准信息。

SDK 实机直读的验证仍待进行。本轮没有做自动来源切换，也没有声称两来源逐元素等价。
仅证明迁移前后的**同一重建方法**在固定输入/基准下保持数值一致。
新 SDK 真 raw 的裁剪/畸变处理到 infer 的流程未完成迁移，不能直接拿任意 raw 图替换现有 infer 输入。

## 文件归属及迁移规则

| 内容 | 当前归属 | 处理 |
| --- | --- | --- |
| 重建适配器/字段校验 | `ros2/omi_sensors/omi_sensors/reconstruction.py` | OMI 源码，进入 Git |
| 原稳定 ROS 发布和看板 | `src/omi_hil_rl/real/tactile_live.py` | 恢复并保留d017387实现 |
| 迁移版 ROS 发布和看板 | `src/omi_hil_rl/real/tactile_live_migrated.py` | 新入口导入共享重建类；renderer 不变 |
| SDK 导入/校验工具 | `omi_sensors.vendor_bundle` | OMI 源码，拒绝覆盖和符号链接，不执行 SDK |
| 厂商运行文件 | `local/vendor/daimon_tactile/` | 本地副本、Git 忽略，不再依赖外部 diamond 路径 |
| CPU 回归/预览工具 | `omi_sensors.reconstruction_check` | 同样本比较数值，可输出参考/迁移后箭头图 |
| 基准、样本与结果 | `local/tactile/` | 本地数据，按资源清单单独备份和恢复 |

导入保留 `dmrobotics/`、`Daimon/` 原生运行库、setup/README/依赖信息及存在的许可声明；
不带 `.git`、build、顶层日志、demo、egg-info 和缓存。不改动外部源目录。
manifest 逐文件记录相对路径、大小、SHA256，核对源文件和副本；校验检查缺失、增加、修改。
缓存 `__pycache__/*.pyc` 不参与哈希。

迁移 manifest 包含原来源路径和导入环境，适合审计，但整个 manifest 哈希会随来源路径变化。
跨机器按 **`sdk_bundle_content_sha256`** 比较实际文件内容；再比较 `baseline_id`、样本 SHA256、
算法版本、Python/NumPy 版本及数值误差。不能只对比 SDK 包名或截图。

## 重建契约保持

CPU / standard、固定 A/B 基准、输入形状约束、同一个 Decomposer 参数均保持不变。
保留原算法版本名和旧 SDK Python 哈希算法，方便比对历史 metadata；完整二进制/模型指纹由
新的 bundle 内容哈希补充。输出仍走已有 ROS 32FC2 和固定箭头绘图参数。
新增 `field_source` 和 `input_representation` 是 metadata 增量字段，不重命名旧 bag topic。
共享类禁止在同进程已加载另一个 SDK 根目录时静默切换 SDK；不同版本请开新进程比对。

## 兼容性和验收

接口纯 Python 部分面向 >=3.10，CPU 实际验收环境为 Python3.12.3 / NumPy1.26.4，
厂商加密模块仍要求匹配的解释器和平台，不因移动目录就获得 Humble/Python3.10 兼容性。
本机已完成 A/B × 23/25.5/28s 共6组历史样本回归，12个场逐元素一致，最大误差0。
保存了6张对照图并查看A在23s的对照图；这不是完整 GUI 人工验收或实机 SDK 对照验收。
详细过程见[迁移编年](../chronicles/2026-10-02-tactile-reconstruction-migration.md)。
后续按用户要求将迁移版与稳定版分离，见[稳定入口保护编年](../chronicles/2026-10-02-stable-viewer-policy-audit.md)。
操作命令见[跨机器复现教程](../../../../tutorials/tactile_reconstruction_migration.md)。
