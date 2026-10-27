# 外部系统与依赖

- OpticalModule与Marvin SDK：原件在local/vendor，维护的ROS接收端在ros2/arm_delta_cmd；实际动态库、工具和控制器兼容性需现场匹配。
- Daimon SDK：触觉采集或raw重建依赖；仅订阅已发布数值场的看板不需要SDK。Python ABI、固件和设备身份必须匹配。
- ROS/RealSense：采集包源码随项目交付；系统ROS、官方驱动、RViz、录制插件和匹配的marvin_msgs需另行安装/构建。不能混用Humble/Jazzy的Python二进制依赖。
- MuJoCo/Gymnasium/SB3：仿真栈，外部MJCF/网格不等于真实设备已校准模型。
- PyTorch：当前真机Actor/Learner为项目自有实现；HIL-SERL/LeRobot是参考项目，不应将本实现称作原版分布式系统。

资源位置和恢复方法见 [本地资源](local-resources.md)、[存储](local-storage.md)、[换机清单](../../tutorials/machine_transfer_checklist.md)。旧机器的绝对路径、设备地址和local文件存在性必须重新核对；文档整理不代表当前主机具备全部运行依赖。
