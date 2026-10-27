# 文档维护规则

项目的默认路线为`docs/README.md → docs/current.md → 任务相关modules`。操作查tutorials，历史只按需读archive。
协作要求见[AGENTS.md](../../AGENTS.md)。

| 内容 | 主要维护位置 |
| --- | --- |
| 项目主线、选定基线、关键未完成问题 | docs/current.md |
| 当前机制、代码入口、验证边界 | docs/modules/ |
| 跨模块字段、单位、数据格式、CLI职责 | docs/interfaces/ |
| 操作者步骤和运行命令 | tutorials/ |
| 长期原则和决定 | docs/decisions/ |
| 待实施方案、验收要求 | docs/design/ |
| 日期过程、旧实验、原文快照 | docs/archive/对应模块/ |
| 验收证据和哈希 | docs/evidence/及登记的local资源 |

更新功能时改写当前模块与教程，其他页引用，不向首页追加整段日期进展。新增实验按日期归档，并更新模块历史摘要。
运行状态标明采样时间、run和证据，不把“最后核查”写成当前实时事实。代码存在、软件验证、现场试用、自主效果分开。
默认值、JSON显式设置、运行时覆盖值分别说明；不同任务的checkpoint、库存和累计预算不能混用。

原文迁移保留正文、命令、实验数字；允许修复链接及添加明确归档标注。证据包保持原字节，必要时保留旧路径跳转。
仓库外local／外盘缺失依赖单列，不将它们假装成已验证的可运行资源。资源登记只改文档指针时，不改机器路径。

修改后运行`python3 scripts/check_documentation.py`检查仓库内链接和锚点，外部依赖缺失另报。
移动时同时核对非Markdown文档指针、图片与校验清单；有历史兼容需求时写短跳转，不保留两份独立现状。
迁移审计材料不属于默认背景阅读。结构和这次完整映射见[重构记录](documentation-reorganization.md)。
