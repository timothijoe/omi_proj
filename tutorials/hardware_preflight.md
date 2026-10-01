# 真机准备：只读阶段

当前仓库**没有可直接执行的真机 CLI**，也没有现场验收过的 IP、SDK 配置和关节限位。先在开发机阅读 [能力边界](../docs/safety.md)与 [SDK 接口](../docs/agent/hardware/evolution/tianji-adapter.md)，并运行无设备自动测试：

```bash
.venv/bin/python -m pytest -q tests/test_tianji_sdk.py tests/test_tianji_sdk_sim.py
```

这些测试不连接控制器。现场只读连接需要设备负责人提供控制器地址、匹配版本 SDK 与动态库、A 臂映射、反馈字段和物理急停流程；真实连接仍需单独授权。`TianjiSdkArm.connect()` 会连接并订阅反馈，即使不切模式也会访问设备。完成只读验收前，不进入运动模式，也不从仿真模型复制限位和速度。异常处理遵循现场设备流程。
