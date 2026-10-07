# 用新 Stand URDF 对照回放

独立入口，不替换旧看板。只读播放已有缓存/录包，不连接机器人或发布控制指令。
前提与[机器人回放](robot_3d_replay.md)一致，另需系统 `libarchive.so.13`。
当前仅在 Jazzy 验证。

在项目根目录运行（路径替换为本机文件）：

```bash
bash scripts/view_stand_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip /home/zhoutong/Downloads/oct2/Marvin_Stand_2026.2.2.rar
```

可加 `0.5` 半速；无图形验证可加 `1 --no-rviz`。关闭 RViz 或终端 Ctrl+C 停止全部子进程。
固定 localhost domain98，与旧 domain97 看板隔离；不要同时开两个新入口。

## 看什么

- 新模型保留 URDF 的关节 origin、axis、限位，不把旧 MJCF 的基座高度带入。
- 带 `URDF L7 origin (NOT flange/TCP)` 标注的小坐标轴是左第七连杆原点。
- 另一组坐标轴为 bag 的 `eef_left`，仍假设其 `base_link` 对应新 `ZJ_Robot_link`。
  该假设未验证；没有添加拟合平移、旋转或猜测的 TCP。
- 图像、触觉和状态面板复用旧录包缓存。没有更换相机或修改裁剪。
- 前七关节对应左臂、后七对应右臂，顺序/符号/零位仍待现场确认。

模型原文件与渲染派生文件保存在 Git 忽略的 `local/robot_state/stand_models/stand-*/`。
只提取 URDF/STL，不执行或导入 SolidWorks 文件；不修改原 RAR。
`model.json` 保存源 SHA256、假设和清理的游离文本（本次原文件中的 `+123456`）。
每次运行创建独立模型目录。`arms.urdf` 使用本机 mesh URI，应在另一机器重新生成，
不能直接复制生成的路径配置。

## 常见问题

- 模型和录包末端不重合不直接证明其中一方错误：还缺基座关系、关节映射和工具变换。
- 本模型没有抓取中心或法兰固定坐标系，L7 原点不是经确认的法兰中心。
- 若 mesh 缺失、关节结构不是这份 Stand 模型或归档不安全，入口直接拒绝。
- 不将模型显示正常理解为运动学或真机安全验收通过。
