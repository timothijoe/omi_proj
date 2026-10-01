# 001：外部场景显式装载

**状态：有效。** 天机 MJCF 与 mesh 作为本地大资源，由 `--scene` 或 `OMI_TIANJI_SCENE` 提供，不把资源复制进 OMI Git。仓库自带的代理模型仅验证接口。原因：场景依赖多份 mesh 与灵巧手资源，分发权限及现场模型版本尚未确认。影响：复现 A 臂实验需先恢复完整外部资源树；教程和 manifest 必须说明路径及来源。[当前实现](../evolution/model-and-task.md)。
