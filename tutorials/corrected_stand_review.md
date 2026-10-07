# Stand 关节方向修正版（只读可视化）

固定命名保存为 `local/models/omi_marvin_stand_axis_corrected_v1/`，
主文件为 `urdf/omi_marvin_stand_axis_corrected_v1.urdf`。**这是OMI派生修正版，不是厂商原版。**
目录内包含15个网格、`source/`中的原URDF、来源哈希和修改说明。
换机器应整体复制此目录，local资源不会随Git提交；网格引用为该资源包的`package://` URI。
该归档的ament构建描述尚未实跑，当前下列已验证回放命令仍读取原RAR并生成派生模型。

```bash
bash scripts/view_corrected_stand_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip /home/zhoutong/Downloads/oct2/Marvin_Stand_2026.2.2.rar
```

与[Stand教程](stand_urdf_review.md)相同的依赖和参数；固定localhost domain94。
本机代表命令使用 bag_004；下文 record001 坐标差与测试数字仍为当时原包实验结果，不能当作 bag_004 的新测量。
关闭RViz或Ctrl+C停止。其他回放入口保留。原始RAR不修改，派生文件位于
`local/robot_state/stand_models/stand-*/`，`model.json`中记录符号映射。

## 修改范围

保留新Stand的支架、全部原始网格、joint origin与根坐标；仅将左3/4/6、右3/4/5
关节axis取反，使输入角度采用旧运动链约定：`q_stand = sign * q_replay`。
不是镜像坐标系，也不是将整台机器人旋转180度；不改变录包数据。
原限位同时按`[lower,upper] → [-upper,-lower]`转换，保持重参数化一致。

## 依据和限制

相对旧模型每侧300组固定seed随机关节角，考虑固定安装变换与L7坐标系变换后：
左臂位置残差最大约2.9e-14米；右臂约2.1e-14米，姿态残差最大约0.000662度
（新右臂部分rpy只保存四位小数）。这是两套模型的数学一致性，不是实机标定精度。

record001缓存约第8秒，修正后L7位置 `[0.34971959,0.04834607,0.79469366]` 米；
录包EEF为 `[0.58229950,0.03470973,0.79588444]` 米。123个同时有状态的缓存样本中，
EEF相对L7的局部平移均值约 `[0.000254,-0.232976,-0.000121]` 米，各轴标准差约
0.060/0.057/0.071毫米；相对姿态旋转角约89.92～90.09度。
这些结果支持固定工具变换的假设，但录包运动范围有限、两种消息非严格同刻，
尚不能确认物理法兰/TCP定义；没有据此新增TCP或修改原始EEF。

**限位尚有不一致，严禁作为控制模型：** 左joint4转换后的限位为
`[-1.0472,2.5307]`，本段136个关节缓存样本约在`[-1.6622,-1.1961]`，全部超出。
回放不裁剪输入，不用修改限位掩盖差异。需要现场确认SDK角度约定与正确机械限位。
录包base_link对应ZJ_Robot_link仍是待核实假设。已有截图能确认模型加载与显示，
不代表模型、工具、碰撞或真实控制验收。
