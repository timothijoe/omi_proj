# 2026-10-03：传感器教程三件套

用户要求腕部、触觉专项和常用汇总共同维护并互相索引。
新增tutorials/sensor_commands.md（速查）和wrist_camera.md（腕部专项），
复用tactile_grid_transport.md作为触觉专项；三者互链，README设主入口。
旧daimon_live保留旧集成看板、依赖和实验说明并指向新主入口，不删除历史教程。
同步纠正残留的“grid永不发raw”“默认发布wrench”等旧措辞，录包示例补入默认depth。
明确raw/wrench显式开关、原raw话题、域匹配、当前实时grid/录包raw显示限制及未同步wrench语义。
本轮只更新Markdown，不重启采集、不改代码、不commit/push。
