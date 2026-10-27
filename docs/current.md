# 项目当前摘要

文档核对日期：2026-10-26，代码基线为`963a7c2`之后的文档整理工作区。
这里描述已实现能力和选定配置；最后一次现场运行快照为10月24日23:06，不报告今天设备或训练是否仍在运行。

## 主线与选定配置

项目面向天机Marvin A臂（左臂）的多模态人工接管学习。真机链路为外部／腕部相机、双指触觉和EEF反馈
→ 十帧策略 → Actor人工／策略仲裁 → ROS接收端 → SDK。独立Learner执行SAC更新；人工夹爪不属于六维策略动作。
MuJoCo七关节到达任务是独立仿真验证路径，不能替代真机验收。

选定参数来自[spacepilot_bc6148_online_rl.json](../configs/spacepilot_bc6148_online_rl.json)，不是所有CLI默认。
BC6148权重初始化空Demo/RL池；SpacePilot、30秒、累计300回合；batch64、1000次Critic预热后触觉解冻，
视觉／融合冻结；after-inference仲裁；人工夹爪开启、Marker关闭；cached共享双池16/20GiB数据预算。
权重每50次更新发布、每10个有效完成回合检查加载。操作见[在线教程](../tutorials/spacepilot_bc6148_online_rl.md)。

## 最新已实现内容

- **独立RViz V2**：九幅相机／触觉图、接收／绘图诊断，底部三列EEF反馈／HUMAN／POLICY bar；原V1保持。
  ROI过期保留末帧并标红STALE；右侧停靠配置缺失已修复。见[可视化模块](modules/visualization.md)。
- **相机断流审计及清理**：旧任务20个回合、30个片段和5681条经验已归档校验后移出活动数据／索引。
  删除台账保持累计回合计数，不返还预算。见[经验池模块](modules/replay.md)。
- **已有训练监控**：网页区分Actor/Learner心跳与主循环进展，展示数据导入和权重交接；还不是统一系统健康监控。

## 最后现场记录：两个任务不能混淆

| 对象 | 目录／快照及含义 |
| --- | --- |
| 原BC | `local/rl_training/spacepilot_bc_20261017_213359_2000_4000`；BC6148来源 |
| 旧任务 | `local/rl_training/spacepilot_bc6148_rl_legacy_30s_300_20261017`；10月24日20:54清理后45994条、权重30897未回滚、累计剩余70 |
| 后续新任务 | `local/rl_training/spacepilot_bc6148_rl_20261024_215949`；初始化记录BC6148、空池、RL计数从0开始 |
| 新任务10月24日23:05快照 | Actor WAIT_START／加载6150，Learner TRAINING／更新6472／发布6450；网页8768指向该run |

主JSON默认run仍是旧任务；续跑新任务必须显式指定`--run`，已有run不再prepare。
这些数字是历史观察，不是当前库存、剩余额度或实时存活证明。新任务初始化记录不证明其后所有数据均已审计。
详见[10月24日完整工作快照](archive/cross-cutting/records/oct24_development_checkpoint.md)和[清理证据](evidence/external_camera_outage_20261024/README.md)。

## 未完成事项

1. **过期输入仍可能采集／入池**：`latest + diagnostic_only_v1`尚未加入统一新鲜度门控。
   断流期间旧RGB进入训练已确认；删经验不撤销旧模型梯度，显示保留末帧也不修复训练链路。
2. **统一健康监控尚未开发**：建议独立后台、RViz总览和现有网页详情共用状态，记录故障时间与受影响回合。
   监控提示、数据门控、动作／回合处置分别定义。见[监控与数据新鲜度方案](design/system-health-monitoring.md)。
3. **控制停止与SDK提交仍有边界**：普通零动作不等于物理即停，拖尾和提交返回值处理需继续验证。见[控制模块](modules/control.md)。
4. **现场持续验收**：相机低频／跨机时间、长时间GUI稳定性、数据质量及无接管自主效果，不能由短测或人工成功标签证明。

当前软件验证：V2相关35项通过，删除台账／训练相关28项通过、2项CUDA专项跳过（10月26日提交前）。
GUI／故障注入为10月24日隔离ROS证据，不等于新的真机验收。
按任务进入[模块导航](README.md)，需要复现历史时才阅读[归档](archive/README.md)。
