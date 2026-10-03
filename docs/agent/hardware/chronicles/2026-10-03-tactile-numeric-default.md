# 2026-10-03：独立触觉采集默认改为低带宽完整数值输入

用户要求原命令`tactile --transport network`默认发布24×16 deformation/shear/depth及六维wrench。
实时启动器tactile默认改为grid24x16，depth/wrench默认开启；新增--no-开关。
显式full恢复旧采集，all/view及底层CLI保留旧默认，避免自动破坏旧看板。
使用独立grid话题，不发送raw/infer；原录包白名单和策略订阅尚未适配。
启动计划与自动测试验证参数组合；不重启现有用户采集，SDK组合真机出流尚未验收。
wrench继续要求同帧六个有限数值，不伪造或降低校验来保证有消息。
这是对前一阶段“默认关闭”的后续变更，不修改当时编年事实。
