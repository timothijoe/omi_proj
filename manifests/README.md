# 本地资源清单

[resources.yaml](resources.yaml) 只记录资源元数据、用途、目标位置与恢复方式，不包含模型、SDK、录制或凭证。`tracked: false` 表示资源本体不应进入 Git。OMI 目前通过显式 `--scene` 使用另一个项目的本地模型资产；没有把它们移动到本仓库。更新资源依赖时同步更新 [本地资源接口](../docs/agent/interfaces/local-resources.md)。
