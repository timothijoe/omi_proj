# 2026-10-02：保护稳定看板及 ROS→策略输入核查

用户要求稳定 `view_observation_bag.sh` 不被后续开发覆盖，新方案另设入口，并核对是否
除TCP以外的传感器均已可用于真机在线RL。

## 稳定入口修正

上一阶段没有修改wrapper本身，但修改了其调用脚本和 `tactile_live.py`，间接改变了稳定链路。
本轮将这两个文件恢复为 `d01738742ff827addef680ee849ffce5ef5a5c78` 的内容；
新代码另存 `tactile_live_migrated.py`、`view_tactile_bag_migrated.sh`，新增
`view_observation_bag_migrated.sh`。未使用破坏性checkout/reset，保留其他未提交工作。

`git diff --exit-code HEAD --` 对稳定wrapper、调用脚本、发布/看板模块、两个RViz配置、
renderer、camera_panels、replay_cache均无差异。专用文件哈希加入manifest和回归测试。
这是文件级回归，不是本轮完整GUI/实机复验，环境/外部SDK仍非不可变快照。

## 代码核查结论

旧ROS adapter有10路topic、NumPy observation和Torch转换；record010的既有离线证据仍有效。
新 `/omi/tactile/*` 数值场/元数据尚未接入旧builder；旧builder还强制取腕部、depth、wrench。
当前独立采集默认关闭depth/wrench，不采集机器人反馈和新腕部流，因此不能直接满足旧observation。
TCP缺失只是其中一项。没有完成新输入契约与实际策略checkpoint的端到端兼容/只读推理验证，
也没有完整真机action/reward/reset/done和在线训练闭环。

已补充[ROS到策略输入方案](../../../design/ros-to-policy-integration.md)，区分已实现、拟实现、
现场验收和未来需授权的动作阶段；未在本轮擅自实现或启动在线控制。
