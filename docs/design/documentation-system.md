# 文档体系与维护规则

`README.md` 和 `docs/README.md` 负责导航；`capabilities.md` 给出跨领域状态。每个真实领域按 `charter`（长期原则）、`current`（摘要）、`evolution`（功能级最新事实）、`chronicles`（按时间永久记录）和 `decisions`（长期架构决定）维护。接口文档记录契约，教程只写操作者可执行步骤。新功能先更新对应纪传体和 current，再按已验证阶段追加编年记录；旧编年记录不改写，错误用新勘误记录纠正。

文档中的实验数字应标明日期、场景与证据等级。不能把参考项目结果写成 OMI 验收。新增 CLI 后核对 `--help`、命令与文件路径；新增本地资源后更新 `manifests/resources.yaml`。大资源和生成结果不进入 Git。旧的 [技术调查](../tianji_hil_rl.md) 与 [实验报告](../a_arm_reach.md) 保留原有背景，当前功能以纪传体为准。
