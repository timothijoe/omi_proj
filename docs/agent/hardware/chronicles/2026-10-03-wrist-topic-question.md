# 2026-10-03：腕部相机准确话题名称核查与议题暂缓

延续[腕部可视化遗留](2026-10-02-wrist-viewer-followup.md)，用户要求核查
`/tj/dm_camera/camera/color`，并查看metadata中的全部话题。

直接读取本机 `/home/zhoutong/Downloads/oct2/record001.zip` 中的
`record001/bag_001/metadata.yaml`：共16个topic、21960条消息，未列出该准确名称。
名称含camera的仅有 `/camera/camera/color/image_raw`（388条）及
`/camera/camera/depth/image_rect_raw`（390条）。已向用户列出全部16个话题。

证据边界：本次核查对象为该ZIP的metadata，不是在线ROS图，也不是其他或更新版本的录包。
不能据此断言设备端没有腕部相机或没有发布该topic；未确定是未启动、未选录、
包版本不一致还是其他原因。没有连接采集设备或修改任何话题映射。

用户要求先放下争论，将问题保留为待核实议题。后续需与采集方核对包版本/路径、
在线发布名称和录包清单；拿到新证据后再决定腕部原图/clip的读取与显示方案。
本轮仅更新纪传体、当前摘要及编年索引，不改代码、不commit或push。
