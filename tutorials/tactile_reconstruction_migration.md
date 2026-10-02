# 在另一台机器恢复触觉重建并做可视化比对

本流程不连接传感器，不创建厂商 Sensor，不要求 ROS；独立数值重建只依赖 NumPy 和厂商 CPU 运行依赖。
箭头预览另需 Pillow 和 OMI 主项目源码。算法仍由厂商 SDK 提供，须取得合法使用许可和匹配的 SDK。

## 准备

从 `omi_proj/` 开始，使用与厂商加密模块匹配的 Python 环境（当前参考包是 Python3.12）。
按厂商提供的版本说明安装 CPU 依赖；不需要为本流程安装 CUDA/CuPy。
旧本机环境为 `local/venvs/daimon312`，其他机器应重建环境，不要拷贝 venv。

```bash
export PYTHONPATH="$PWD/ros2/omi_sensors:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
# 首次导入。将 SOURCE_SDK 改为合法取得的 SDK 目录，不要求 diamond 工程存在。
python -m omi_sensors.vendor_bundle import SOURCE_SDK local/vendor/daimon_tactile
python -m omi_sensors.vendor_bundle verify local/vendor/daimon_tactile
```

目标目录必须不存在。若已有本地归档，直接 verify；不要覆盖。导入失败会留下待检查目录，
不会删除用户文件；重试用新目录。导入工具不安装依赖、不执行 setup.py、不修改 SDK。
新迁移版可视化默认指向 `local/vendor/daimon_tactile`；自定义位置用 `OMI_DAIMON_SDK_ROOT`。
原稳定入口保持外部SDK默认位置不变。

## 恢复基准和样本

从实验归档恢复以下两个完整目录，数据本体不进 Git：

- `local/tactile/record010_zero_load_25_26_confirmed_v2/`：metadata.json、A/B 基准 NPY。
- `local/tactile/record010_offline_fields_confirmed_v3/`：`a_*.npz`、`b_*.npz` 六个样本。

样本含 raw/infer 输入和历史 deformation/shear 参考输出。基准 metadata 参与哈希，
比对时不要自行重写里面的身份和来源字段。资源位置见 `manifests/resources.yaml`。
若没有原始参考数据，只能做新实验，不能把新生成的数据冒充这次迁移的历史对照。

## 数值比较和箭头预览

```bash
python -m omi_sensors.reconstruction_check \
  --sdk-root local/vendor/daimon_tactile \
  --baseline-dir local/tactile/record010_zero_load_25_26_confirmed_v2 \
  --fixtures local/tactile/record010_offline_fields_confirmed_v3 \
  --output local/tactile/my-machine-comparison.json \
  --preview-dir local/tactile/my-machine-preview
```

不需要图片时去掉 `--preview-dir`，无需主项目 renderer/Pillow。
输出路径必须不存在。每张图左列是历史参考、右列是迁移后结果；上排 deformation、下排 shear。
箭头长度比例一致，红色仍只表示超过显示截断长度，不表示力异常。
默认容差 `atol=1e-6, rtol=1e-5`；报告含逐字段最大误差、MAE、exact/passed。
超出容差返回非零，不会自动修改算法或放宽阈值。

比较报告时先确认 SDK 内容哈希、基准和样本 SHA256 一致，再看环境与数值；
仓库内的 `manifests/tactile-reconstruction-reference.json` 保存本次参考指纹，不含样本本体。
当前机器六组样本 exact=true，不保证换CPU/库版本之后必然位级一致。

## 显式选择迁移版可视化

```bash
bash scripts/view_observation_bag_migrated.sh BAG
```

这是单独命名的 Jazzy/Python3.12 组合看板，调用迁入独立包的重建类，默认使用本地SDK。
单独 `python -m omi_hil_rl.real.tactile_live_migrated ...` 时先 `source scripts/env_ros.sh` 或设置上述 PYTHONPATH。
原 `bash scripts/view_observation_bag.sh BAG` 仍走恢复后的稳定旧链路，未自动替换。
两个入口使用相同默认domain/topic，不要同时启动。
独立 ROS 包安装后也可以 source 其 overlay 获取 `omi_sensors`；主训练包的 pip 安装不自动安装这个独立包。
CPU 回归不等同于看板实时性能验收，也不等同于与实机 SDK 输出等价。
