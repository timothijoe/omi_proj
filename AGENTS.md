# 项目文档与协作规则

## 默认阅读路线

先读`docs/README.md`和`docs/current.md`；按任务选择`docs/modules/`，需要精确契约再读`docs/interfaces/`，
需要操作步骤查`tutorials/`。同一会话读过且未变化的内容无需重复读取。
用户明确要求全部阅读或历史审计时按其范围执行。

默认不全文读取历史归档。当前说明和代码无法解决具体问题，或需要追溯实验、设计原因时，
先读`docs/archive/<模块>/README.md`，再选择原始记录。机械盘点、链接校验可以扫描归档。

```bash
rg -n --glob '*.md' --glob '!**/archive/**' '关键词' docs tutorials
```

## 事实与证据

- 配置／代码决定实现行为，带日期的证据说明实际验收；计划、软件测试、现场试用与自主策略评估分开。
- CLI默认、选定JSON配置、某次运行的覆盖参数分开。最后一次LIVE／CLOSED记录不证明现在的进程状态。
- 最新记录中的新旧run要区分；当前JSON默认run仍可能指向旧任务，操作前核对显式`--run`。
- 接收心跳不等于主循环推进；消息新鲜不等于曝光新鲜；命令接受／SDK提交不等于物理动作完成。
- 资料冲突时查相关代码与最新适用证据，说明差异，不从旧目录复制运行结论。
- 文档整理不会自动授权启动机器人、训练、删除数据或改变现场进程；按用户任务范围执行。

## 维护位置

当前项目摘要在`docs/current.md`，模块机制在`docs/modules/`，接口在`docs/interfaces/`，
操作在`tutorials/`，长期原则在`docs/decisions/`，未完成方案在`docs/design/`。
过程和实验记录进入`docs/archive/<模块>/`，不要再向首页和current不断追加整段编年。
`docs/agent/`残留页只为校验过的证据包保留旧链接，不是第二套现状文档。

修改后运行`python3 scripts/check_documentation.py`，核对链接／锚点、迁移映射及非Markdown引用。
证据包及其SHA256SUMS覆盖的文件保持原字节；如需要修正说明，另加记录并保留来源。
本地模型、数据、SDK和外盘资源不随Git完整交付。维护规范见`docs/design/documentation-system.md`。
