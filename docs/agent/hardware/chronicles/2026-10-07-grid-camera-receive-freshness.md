# 2026-10-07：实时grid看板外部RGB按接收时间显示

用户反馈 `bash scripts/view_grid_observation_live.sh --hz 10` 的第三视角相机闪烁，指出图像来自另一台机器，源header与本机时钟可能存在偏差。

看板原先要求本机接收年龄和源header年龄都不超过250ms才显示。已有session状态文件中，外部RGB一次接收年龄约1.09ms、header年龄约261ms，状态为`OLD_HEADER`；另一次接收年龄约1.21ms、header年龄约249ms，状态为`LIVE`。这证明源header阈值可在接收持续新鲜时切换画面状态；仅凭这些快照不能确定源图像的真实端到端时延，也不能排除现场还有其他闪烁原因。

本次仅改只读 `grid_live_review` 的外部RGB显示判定：有效图像按本机单调接收年龄≤250ms显示；源header年龄继续写入`status.json`和状态栏，供诊断。共享回放布局内该相机的年龄标签也改用接收年龄，源时间戳原值保持不变。其他相机、触觉、EEF和策略输入时间门控没有改动；接收超过250ms仍隐藏旧图。

专项测试8项通过，覆盖源header早/晚而接收新鲜、接收过期隐藏、渲染标签及原时间戳不变。`git diff --check`通过。未连接现场相机重跑RViz；需现场重新启动看板观察闪烁是否消失，并对照`receive_age_ms`、`header_age_ms`及接收Hz检查真实断流或渲染负载。
