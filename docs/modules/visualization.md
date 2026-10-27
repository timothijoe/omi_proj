# 实时可视化与训练监控

实时图像、机器人反馈、训练遥测和历史回放服务于不同问题。查看器只发布显示／诊断，不发布控制指令，
不能用显示正常证明训练数据新鲜，也不能用命令回执证明实际到位。

## RViz V2：当前实时入口

```bash
bash scripts/view_grid_observation_live_v2.sh --hz 10
```

原版`view_grid_observation_live.sh`保留，八个文件基线由`manifests/live-grid-viewer-v1.json`验证。
当前V2布局为相机／A触觉／B触觉三行三列：外部原图、外部128 ROI、腕部ROI，以及两指的deformation／shear／depth。
Wrist full、A raw、B raw已从查看器移除，未关闭上游发布。三维区显示修正版Stand与EEF/L7。

外部原图和腕部ROI由RViz直接订阅；外部ROI及六个触觉场分别在独立进程转换，只保留最新待处理图，
不逐帧保存PNG。独立probe统计输入与输出，diagnostics显示接收年龄、频率、绘图耗时和worker心跳。
单个worker异常不关闭其他面板；RViz／probe／diagnostics退出时主程序清理本次查看器。
同domain锁防止重复实例，查看器退出不停止外部采集和训练。

底部右侧有三列bar：绿色**END EFFECTOR**为反馈XYZ mm／ZYX RPY°，蓝色**HUMAN**和紫色**POLICY**为最近收到的六维指令。
末端显示比例±1500mm／±180°；命令默认±1.5mm／±1°（SDK ABC）。比例不同，条长不能直接对比。
末端源为`/tj/info/eef_left`；人工／策略通过接收端参数只读解析，也可CLI覆盖。两列不推断实际控制权。

指令250ms、末端／回执500ms未更新标STALE，条变灰保留旧值；非法／缺失不伪造零值。
外部ROI过期保留像素并加红框和STALE秒数；触觉过期显示占位。原图或已退出worker可能保留最后一帧，必须结合诊断。
接收年龄不等于曝光延迟，绘图publish耗时不包含RViz最终呈现。所有面板仍共享GUI/GPU。

面板整体消失要检查布局：模板及运行时已补`Hide Right Dock: false`；F11全屏和侧边折叠也会隐藏面板。
用户描述的延时自行消失尚未复现，修复配置缺陷不代表找到唯一原因。恢复步骤见[V2教程](../../tutorials/grid_live_review_v2.md)。

实现：[grid_live_v2.py](../../src/omi_hil_rl/real/grid_live_v2.py)、[core](../../src/omi_hil_rl/real/grid_live_v2_core.py)、
[control](../../src/omi_hil_rl/real/grid_live_v2_control.py)。35项回归及10月24日隔离ROS GUI／故障注入通过，未替代长期现场验收。

## 已有训练网页与统一监控待办

[view_training_monitor.sh](../../scripts/view_training_monitor.sh)只读指定run，显示Actor/Learner、保存导入、回合审阅与权重交接。
`TelemetryWriter`约2Hz快照，`emitted_ns`与`progress_ns`区分心跳和主循环进展。旧快照、退出和断连不能显示成实时正常。
正常WAIT_START／等待数据不等于故障，需要结合阶段判断。网页与V2各自独立，不是启动V2就自动监控整个系统。

**统一系统健康后台尚未实现。** 建议独立采集、RViz摘要、现有网页详情共用状态，记录故障开始／恢复和受影响回合。
旧网页`--sensor-status`桥接V1的status／dashboard，不能直接当作V2接口。
实现顺序与验收见[监控设计](../design/system-health-monitoring.md)；告警与阻止旧图入池分别开发。

## 回放与辅助工具

历史bag显示见[RViz代表录包](../../tutorials/rviz_representative_bags.md)，训练数据检查见[逐帧审阅](../../tutorials/rl_episode_visual_review.md)。
录包缓存可能依赖外盘，实时V2不依赖这些录包缓存。Stand显示模型不是控制模型／TCP标定的替代验收。
六关键点审阅是独立工具，合成测试标注不进入真实训练。
历史过程见[可视化归档](../archive/visualization/README.md)。
