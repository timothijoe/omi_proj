# 2026-10-03：通用小矩阵RViz回放入口

用户授权先开发通用可视化，再讨论raw发布。新增`view_grid_observation_3d.sh`与
`grid_recorded_review.py`，不再依赖临时local代码或固定bag路径。
支持ZIP/MCAP目录、ROI直显、384向量/场、depth、已有wrench、关节模型与EEF；
默认domain92，带同入口域锁、倍速、prepare-only、strict-clock和限时无GUI选项。
复用原缓存读取器时增加显式decoder与allow_future_headers参数，旧入口默认严格行为保留。
缓存保留原header并记录时间警告，不回放控制话题、不采集硬件。

验证：相关测试在项目venv中17通过2跳过，SDK/ROS环境19通过，包含ZIP/目录模拟读取、
时钟严格/宽容分支、原时间戳保留、384向量、ROI直显、旧显示回归。
系统Python初次测试因缺gymnasium未能收集，改用已有SDK/ROS环境通过，未安装额外依赖。
`oct3_022/bag_001.zip`实际准备成功，RViz截图确认相机、数值场、depth与3D模型显示。
A三场353/354/354、B三场各363帧，wrench仍零条；触觉header最大超前约29ms，
不宣称时间同步或六维力验收。GUI试运行使用40秒自动停止，不影响已有回放或实时驱动。

操作见[教程](../../../../tutorials/grid_bag_review.md)。raw发布仍未开发；未commit/push。
