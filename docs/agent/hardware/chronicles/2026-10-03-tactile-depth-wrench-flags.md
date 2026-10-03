# 2026-10-03：触觉深度与六维力启动开关

检查oct3_010/bag_004时发现两指depth/wrench话题各为零条消息；当前启动模板两项默认关闭。
用户要求开启深度并保留六维力/力矩，新增`--tactile-depth`与`--tactile-wrench`，
支持full/grid24x16、network传输及view订阅配置；默认行为不变。
SDK已有enable_depth/enable_force及getDepth/getForce适配，沿用同帧、有限数值检查。
不放宽无帧号wrench的拒绝规则，不虚构标定单位；硬件是否返回合规数据仍需验收。
开关组合的启动计划测试和SDK模拟快照测试通过。未重启用户现有采集进程，未做真机出流验收。
操作见[教程](../../../../tutorials/daimon_live.md)。
