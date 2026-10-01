# 开发环境重建

前提：Python 3.12、`uv`、当前仓库源码。先在 `omi_proj/` 中创建虚拟环境；`uv` 从软件包索引安装依赖，需可用网络或本地缓存。

```bash
uv venv .venv --python python3.12
uv pip install --python .venv/bin/python -e '.[dev,viz]'
.venv/bin/python -m pytest -q
```

训练另需 PyTorch 与 Stable-Baselines3。需要 CPU 版 PyTorch 时可用：

```bash
uv pip install --python .venv/bin/python filelock jinja2 networkx sympy
uv pip install --python .venv/bin/python --no-deps torch --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/bin/python -e '.[dev,train,viz]'
```

预期 `pytest` 运行仓库自动测试；若未提供 `OMI_TIANJI_SCENE`，外部 MJCF 测试会跳过。环境变量指向完整场景后可运行该测试。虚拟环境在 `.venv/`，不进入 Git。缺模型时仍能运行自带代理的 `.venv/bin/python -m omi_hil_rl.sim.smoke`。停止测试用 `Ctrl+C`。
