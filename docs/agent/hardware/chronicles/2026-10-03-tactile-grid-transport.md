# 2026-10-03：触觉数值场24×16可选传输

## 目标与实现

用户要求保留当前功能，另实现发布前预处理的24×16低带宽版本。
新增`tactile_grid.py`及独立`start_daimon_tactile_grid.sh`，沿用原SDK采集和同帧校验，
对288×384的deformation/shear做18×16区域平均，输出高16宽24两分量float32。
全模式默认保持原样；低分辨率使用独立话题、metadata schema3，不发raw/infer。
省去大数组的ROS消息构造/传输，但SDK接收和快照仍是完整数据。

## 证据与限制

自动检查包括源形状/有限性、轴方向、幅值、与训练pool_field一致、288倍载荷比例、
旧模式对象不改动、启动计划参数传递和旧看板保护。
相关六个测试文件在项目venv中60项通过、6项跳过（含缺ROS环境项）；
系统Python单独执行ROS集成测试2项通过。脚本`--plan`、Shell语法及`git diff --check`通过。
Jazzy合成源在独立发布/订阅进程中验证full及grid两模式的双指消息、尺寸、编码和metadata。
首轮集成测试失败是测试子进程覆盖PYTHONPATH丢失ROS路径，保留原路径后两项通过。
本阶段没有连接真机、运行RViz、控制机器人或录制硬件数据；Humble/跨机器/长时间吞吐未验收。

理论双指两个场30Hz净载荷106.17→0.369 MB/s，不是整个系统/SDK链路减少288倍。
平均不可逆，有局部接触弱化、相反向量抵消风险。保留完整场对照再评估插孔任务训练。
旧策略、看板及录包白名单尚未适配；教程给出显式测试录包命令。不创建commit或push。

当前权威说明见[纪传体](../evolution/tactile-resolution-and-throughput.md)，
操作见[教程](../../../../tutorials/tactile_grid_transport.md)。
