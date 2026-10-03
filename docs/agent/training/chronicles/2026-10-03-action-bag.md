# 2026-10-03：Float64MultiArray 动作包与模拟控制端联调

用户要求记录并测试末端动作：沿三个方向各5cm、绕三个轴旋转，再执行逆动作返回。
实现 `real/eef_action_bag.py`、`scripts/eef_action_bag.sh`，每帧六维米/弧度增量，
与既有基座系 EEF 动作数学定义一致。默认右为 -Y、旋转各10°，作为待现场确认的实验参数。

10Hz、每段2秒、12段240帧，五次曲线分配增量；返回严格反序取负。
真实 rosbag2 MCAP 回放通过 DDS 进入模拟控制端；接收动作和生成的目标重新录包。

本机结果：

- `local/action_test/xyz_rotation_v1/commands`：240条动作；manifest含阶段、时间和预期位姿。
- `local/action_test/xyz_rotation_verify_v1/received`：240条实际接收动作、240条模拟目标。
- `local/action_test/xyz_rotation_verify_v1/report.json`：passed=true，逐帧目标误差0。
- 返回误差：平移分量约6.39e-18 m，旋转分量最大1.75e-16 rad。
- 实际接收间隔0.09852–0.10147秒，中位数0.100003秒；首末消息跨度23.90006秒。
- 全套测试168 passed、6 skipped；本次新增8项轨迹/异常输入测试。

没有连接或运行真机；理想模拟反馈立即等于目标，未验证动力学和真实2秒执行效果。
尚缺经过验收的笛卡尔控制衔接、实测反馈以及现场坐标和TCP确认。
MultiArray缺少时间和序号；已知轨迹比对不能替代一般在线流的过期/重复检查。

最新接口与操作见[教程](../../../../tutorials/eef_action_bag.md)。
