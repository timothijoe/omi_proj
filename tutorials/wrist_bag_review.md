# bag_004腕部相机＋触觉＋机器人RViz回放

外部与腕部两套裁剪的文字基线见[双相机ROI第一版](../docs/design/camera-roi-v1.md)，
包括相对参数、实际像素边界与显示/训练插值方式的区别。

已知限制：bag_004的腕部画面近乎静止，原始图像、缓存和实时发布逐级比对相符。
怀疑采集端但尚未定位，用户要求暂缓；不是更换ROI就能修复。
只看时间戳或像素哈希变化不足以证明视频有效更新。后续需在镜头前挥手/遮挡的短包验证。

在项目根目录运行：

```bash
bash scripts/view_wrist_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip
```

本机代表数据路径为 `/home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip`；完整一行式命令见[三包 RViz 操作页](rviz_representative_bags.md)。旧 Downloads 路径只保留兼容链接。
可加`0.5`半速；`1 --no-rviz`只启动显示数据发布。关闭RViz或Ctrl+C结束。
固定localhost domain93，不能在相同domain重复启动。无设备连接、无控制指令回放。

## 看板布局

- 左上：外部彩色原图与既有128 ROI。
- 右上：`/tj/dm_camera/camera/color`腕部原图与128×128裁剪预览，放大显示。
- 中间：两侧deformation和shear数值场箭头图。
- 左下：两侧触觉depth；右下：两侧原始触觉图。
- RViz模型：命名的OMI方向修正版；L7原点与录包EEF分开显示，不补猜测TCP。

腕部复用旧`view_observation_robot_bag.sh`的ROI：中心比例`(.500,.704)`、边长为短边的`.36`。
对1920×1080原图取`x=766,y=566,side=389`，Lanczos缩至128×128，再双线性放大供查看。
黄色框显示裁剪区域；128预览与旧看板像素一致，仍需检查是否适合新任务画面。
这是crop，不是去畸变；CameraInfo的distortion_model为空，本入口不尝试纠正畸变。
bgr8源图通过共享解码转换成RGB。看板预览不直接作为策略输入；
新[EEF v2策略](eef_action_space.md#6-开启或关闭腕部相机v2)独立解码腕部原消息、裁剪并最近邻缩放。
旧BC契约与本看板Lanczos显示保持。

## 依赖、缓存与模型

依赖Jazzy/RViz/robot_state_publisher、匹配的Marvin消息overlay和项目Python环境；
配置仍读取`local/robot_state/viewer.env`。与其他原生字段入口一样，不需要触觉SDK。
直接读取`local/models/omi_marvin_stand_axis_corrected_v1/`，解析本地mesh路径；
不需要原RAR，不再次翻转关节，模型身份检查拒绝普通厂商原版。
换机器整体拷贝该模型目录；可用`OMI_WRIST_MODEL_BUNDLE`覆盖目录。

首次解压并生成独立`local/wrist_recorded_review/`缓存，需要几GB临时空间；
当前版本`wrist-review-v2-legacy-roi-lanczos-128`，此前中心大方框v1缓存保留但不再读取。
源图裁剪和绘图在准备阶段完成，播放只读缓存。缓存不混用旧版本，不修改旧脚本布局。
缺腕部时对应区域显示WAITING，不用触觉或外部相机冒充。
源时间年龄大于250ms标STALE，开始约0.86秒无关节反馈时仍按旧播放器显示零位占位，
不能把占位当作实测姿态。模型base/TCP/限位限制仍见[方向修正版说明](corrected_stand_review.md)。

bag_004的18话题、12820消息已全部解码核对数量；腕部345帧，内参346条。
没有TF/TF_static、外部CameraInfo；最长触觉接收间隔约409ms，不能用该看板证明硬同步。
