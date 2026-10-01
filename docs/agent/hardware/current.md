# Hardware 当前摘要

`TianjiSdkArm` 已封装 SDK A/B 反馈索引、度/弧度换算、反馈帧与错误检查、显式运动授权、单步和关节范围检查、位置模式与停止/释放。假 SDK 与 MuJoCo 替身测试通过；没有设备只读连接记录，没有真机运动验收。项目也没有面向操作者的真机控制 CLI。

当前 API 与限制见 [Tianji 适配器](evolution/tianji-adapter.md)；形成阶段见 [编年记录](chronicles/2026-10-01-sdk-boundary.md)。近期需要现场设备配置和只读反馈验收。
