# 2026-10-03：grid模式raw与wrench显式开关

用户要求raw明确写出才发送，并建议wrench同样处理。新增`--publish-raw`，通过启动器、
CLI子进程传到发布节点；grid额外发布`/omi/tactile/{a,b}/raw`，原尺寸、同快照、无压缩。
infer仍省略；wrench默认从开启改为关闭，需`--tactile-wrench`。三场含depth默认不变。
为保留旧看板，显式full模式仍按旧规则发raw/infer。
新增ROS合成测试验证raw开关、原话题、编码和metadata。运行中的真机驱动不热更新、不重启；
它仍保留之前启动时启用的wrench。下一次启动才采用新默认。
raw显示未接入grid回放器，旧包不能补原图。本轮没有硬件raw组合验收。未commit/push。
