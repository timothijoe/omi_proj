# 2026-10-07：异步 RL 手柄 Back 回 home 与 A/B 夹爪修复

## 现场反馈与原因

用户运行 `scripts/run_async_rl.sh --run local/rl_training/async_20261007_20s_01 --execute --enable-policy` 后，
发现 Back（314）不能回 home，A/B 不能开合夹爪；直接采集入口已有这两项功能。

异步入口虽然复用回合采集逻辑，但创建传输层时未传入 `home_button_code` 和 `GamepadGripper`，
因此 `RosTransport` 无法处理这两个控制。共享的 `RoutedTransport._publish` 也未转发
home 指令使用的 `convention` 等关键字参数。另查到异步入口使用的 `local/cuda-env`
缺少夹爪 SDK 所需的 `grpcio` 和 `protobuf`。

## 修复

- `hil/async_training.py` 默认启用 Back 键码 314 和与 `gamepad_test.py` 一致的 A/B 夹爪参数；
  增加 `--home-button-code`、`--no-gripper`，校验按键冲突，并启用按键日志。
- 共享的 `hil/alternating.py:make_transport` 检查实际手柄包含所需按键，
  将 home 和夹爪对象传给 `RosTransport`，启动夹爪连接；指令路由转发 home 所需参数，
  让回位命令经接收端手动话题发送。交替入口没有启用这些新参数。
- 在本机 `local/cuda-env` 安装 `grpcio`、`protobuf`；重建环境时需重新安装夹爪 SDK 依赖。
- 回合等待提示只在传输层确实有 home 功能时才显示 Back 提示。

## 运行语义与验证

Back 单按只在回合外（等待、保存、加载或暂停阶段）触发自动回 home；
正在录制的 ACTIVE 回合内不触发。A（304）闭合、B（305）张开，回合内外均可使用，
无需按 RB；按键释放后才能再次触发。夹爪动作不作为六维 RL 动作标签。

修复后须先用 Ctrl+C 结束旧进程，再重新运行原命令，让进程加载新代码。
软件回归：`test_async_training.py`、`test_alternating_rl.py`、`test_rl_episode_collection.py`、
`test_gamepad_home.py`、`test_gamepad_gripper.py` 合计 **67 passed**；`git diff --check` 通过。
CUDA 环境中夹爪 SDK 导入成功。未发送真机动作，Back 回位和夹爪实物开合仍待现场确认。
若仍无反应，保留启动日志及按键时的按键状态日志，核对手柄键码与夹爪连接。
