# 2026-10-04：禁用关节反馈的GPU训练

用户要求训练不使用关节反馈、带输入标记的新版本，并指定GPU。
新增`eef-current9stack-no-joints-v1`：关节七维在归一化前和融合时屏蔽，
每时刻joint_mask=0，joint_enabled=0随权重保存；保留末端位姿、双视觉、触觉及十时刻历史。
原数据、原模型产物保留。增加CUDA训练/加载与独立版本检查。

同oct03_split2划分1283训练/242验证，seed7、batch32、2000步、RTX5060Laptop FP32，
179.88秒完成。best1300步验证0.790943mm/0.00321688rad，归一化MSE0.804735；
相对原CPU含关节模型平移高2.48%、旋转低0.44%，不是同设备单因素因果证明。
last2000步验证0.805240mm/0.00331479rad，仍有后期过拟合。

13项相关测试通过；32真实窗口关节NaN不影响动作；同精度CPU/CUDA最大动作差3.42e-8；
旧模型8窗口回归最大差1.40e-9；冻结参数未变、best重载及缓存路径检查通过。
两次短跑失败分别是CUDA确定性adaptive pooling缺实现、替代核尺寸错误；
修正为8×12→2×3的4×4平均池化并通过值/梯度等价测试，第三次短跑及正式训练完成。
独立数值核验曾因默认TF32与训练条件不同失败，关闭TF32后通过，未放宽阈值。

产物`local/eef_history/oct04_nojoints_cuda_run1/`，详见[纪传体](../evolution/nojoint-stack.md)
与[教程](../../../../tutorials/nojoint_stack_training.md)。原始训练日志在同级.log，失败短跑单独保留。
没有上线ROS节点、启动执行器或解决base_link/A_base标定。没有commit/push。
