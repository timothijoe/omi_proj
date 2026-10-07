# 新外观与旧运动链对照

此实验入口保持旧模型全部14个活动关节及根固定关节不变，仅替换可对齐的显示网格。
不使用新 Stand URDF 的关节角定义，不校准基座或 TCP，不发布控制指令。
原[旧模型入口](robot_3d_replay.md)及[新URDF入口](stand_urdf_review.md)保留。

```bash
bash scripts/view_hybrid_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip /home/zhoutong/Downloads/oct2/Marvin_Stand_2026.2.2.rar
```

参数与 Stand 入口相同：可加播放速率，以及 `--no-rviz`。固定 localhost domain95。
关闭 RViz 或 Ctrl+C 停止。准备网格约需一分钟；依赖原回放环境、NumPy、SciPy、
PyYAML、系统libarchive和旧场景资产，不需联网下载依赖。

## 本次组合范围

- 新网格到旧网格采用固定随机种子的点云刚性配准，仅调整 visual origin，不缩放、不镜像。
- 两侧1～4、6使用新网格；两侧5、7保留旧网格。第七连杆含不同工具几何，不强行配准。
- 判据为采样点双向最近邻距离的90分位最大值小于8毫米；这是外观筛选阈值，
  不是机械标定精度或严格曲面距离。对称网格可能存在方向歧义，仍需目视检查。
- 支架新网格仅在旧root下平移Z=-0.90205米，以对应肩部高度；保留旧肩部安装件。
  新旧安装宽度可能不同，没有拉伸支架、移动运动关节来掩盖差异。
- 保留旧world/root导致支架底部低于原网格地面，故新配置隐藏Ground，不宣称已建立地面坐标系。
- 录包EEF仍按旧base假设显示，L7原点不当作法兰或抓取中心；不因外观变化修改数据标签。

派生资源位于忽略的 `local/robot_state/hybrid_models/stand-*/`。
`hybrid.urdf` 是最终模型；`hybrid_report.json` 保存各连杆配准矩阵、误差和回退原因。
`arms.urdf` 是中间的新Stand模型，不能与最终hybrid文件混淆。
当前只验证Jazzy、本机回放；未验证真机正确性。
