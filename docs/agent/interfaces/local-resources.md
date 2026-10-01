# 本地资源定位

当前 A 臂场景通过 `--scene` 或 `OMI_TIANJI_SCENE` 定位，路径须指向完整 `cooking_proj/local/assets/robot_assets/mujoco/right_chopping_scene.xml`；其相对 mesh 引用还需要相邻的 `MarvinCCS` 与灵巧手资源。当前工作区不包含这些非跟踪资产。本机过去在另一份检出中加载过场景，但文档和代码不依赖那台机器的绝对路径。恢复所需资源见 [manifest](../../../manifests/resources.yaml)。

manifest 约定将来可把模型和 SDK 恢复到仓库的 `local/`；该目录目前没有迁入现有资产，且由 `.gitignore` 排除。当前生成文件写在 `data/`，虚拟环境在 `.venv/`，同样被忽略。已选的一张验证 PNG 和一段小 GIF 放在 `docs/evidence/` 作为可审阅证据。没有迁移或删除用户已有资源；真正恢复到 `local/` 前须确认资源权限与路径。
