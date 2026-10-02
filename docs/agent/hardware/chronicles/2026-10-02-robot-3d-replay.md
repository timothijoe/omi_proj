# 2026-10-02：从文字状态到RViz双臂3D回放

用户指出文字看板没有在3D界面显示机械臂，并授权增加纯回放3D视图。
本轮沿用现有未提交文字看板工作，不重置、不覆盖旧稳定入口，也不连接硬件。

## 处理

项目本地没有可直接使用的URDF，但已有双臂MJCF和MarvinCCS网格。
先向用户说明模型不含匹配现场的触觉夹爪；转换明确的14轴链生成RViz-only URDF，
排除场景中的灵巧手、刀具和道具，不伪造工具TCP。
新增独立脚本、RViz配置、robot_replay_3d模块及测试/检查脚本。
按历史反馈而非目标命令驱动模型，采用独立joint_states、TF、robot_description和状态话题。
RViz布局为控制项/3D/观测并排，状态Marker明确标注回放与未标定边界。

## 验证

- 全套116 passed、5 skipped；新增3D/文字面板/旧冻结文件定向10 passed。
- 生成URDF的15个body变换（基座及双臂14连杆）与MuJoCo FK在非零测试关节角下对照，
  位置和旋转误差满足1e-8容差；资产在本机实际存在，因此本轮该测试未跳过。
- 第一次真实GUI检查：42秒、2倍速、隔离domain98，330条关节状态、333条TF、345帧看板；
  确认关节变化、回放循环、模型描述和静态TF，无控制topic、无全局joint_states。
- 截图确实显示双臂mesh。随后修正Marker配置键为Topic，并固定并排dock布局；
  检查脚本补充RViz确实订阅状态Marker的断言，再跑GUI验证。
- 最终加宽布局复验：330条关节、333条TF、345帧看板；循环、模型描述、静态TF、
  无控制topic、无全局joint_states及RViz Marker订阅全部通过，日志无ERROR/Traceback。
- 证据：`local/robot_state/3d_check/{report.json,run.log,rviz_desktop.png}`。
  该目录保存最近一次检查，复跑会更新，不是首次结果的不可变归档。
- 没有启动机器人驱动/控制器，没有回放关节或夹爪命令；旧稳定文件哈希测试通过。

## 未证明事项

未做物理机器人模型匹配、关节方向/零点标定、夹爪模型、工具TCP或碰撞校验。
本轮为Jazzy显示验收，不是Humble验收、实时30 Hz完整数据压力测试或模仿学习数据验收。
新增实现仍未自动commit。详见[当前功能](../evolution/robot-3d-replay.md)。
