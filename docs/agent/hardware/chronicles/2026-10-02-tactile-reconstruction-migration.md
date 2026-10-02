# 2026-10-02：触觉图像重建适配器与 SDK 本地归档迁移

## 目的

用户希望把当前“图像生成触觉数值场”的方案纳入自己的包，注明迁移方案与过程，
便于其他机器复现；长期以 SDK 直接采集/录包为主，目前用可视化判断正确性。

## 实际过程

1. 检查参考 SDK：`dmrobotics/src/dmSDK.py` 为 PyArmor 加密文件，未发现明确再分发许可。
   不进行解密或自主算法重写，选择“自有适配器入源码 + 厂商运行依赖本地归档”。
2. 从 OMI 原 `tactile_live.FieldProcessor` 提取共享类到 `omi_sensors.reconstruction`。
   CPU/standard、固定基准、Decomposer 参数、版本字符串和输出 shape/dtype 保持。
3. 新增 vendor_bundle import/verify；本机归档54个文件到 `local/vendor/daimon_tactile`，
   约358 MiB，包含模型与原生运行库，排除参考仓库历史/构建/顶层日志/缓存。
   没有修改外部目录；SDK 本体不进 Git。
4. 原回放看板改用共享类，默认 SDK 路径改为项目 local；添加来源/输入类型元数据。
   SDK 直读 metadata 同时标注 `sdk_direct`，未做自动切换。
5. 用已有v3样本运行独立CPU回归，再生成参考/迁移后对照PNG。

## 结果与证据

- A/B × 23、25.5、28s：6个样本，12个 deformation/shear 场；shape均288×384×2float32。
- 与迁移前参考数组逐元素相同，最大误差0、MAE0。
- 报告：`local/tactile/migration-check-20261002.json`、`migration-visual-check-20261002.json`。
- 图片：`local/tactile/migration-preview-20261002/` 共6张；查看A/23s的左右对照，绘图方向/截断一致。
- 迁移单元测试与原项目回归：87 passed、4 skipped（主环境缺少PyYAML等可选条件）；Jazzy colcon构建通过。
- 当前数值验收 Python3.12.3 / NumPy1.26.4，CPU。没有连接硬件，没有启动机器人控制。

## 边界

迁移的是可维护的调用层和依赖组织，不是厂商算法所有权或可读源码。
旧样本所谓raw实际为mono8 infer；未验证真正SDK raw直接作为输入。
本次证明迁移前后重建相等，不证明图像重建与实机 SDK 直读相等。
未进行Humble、其他机器、SDK在线或完整GUI验收。没有创建commit，没有push。

[当前方案](../evolution/tactile-reconstruction-migration.md) ·
[复现教程](../../../../tutorials/tactile_reconstruction_migration.md)
