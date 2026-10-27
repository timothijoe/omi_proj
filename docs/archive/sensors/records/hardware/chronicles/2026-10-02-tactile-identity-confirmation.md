> 历史资料：原路径 `docs/agent/hardware/chronicles/2026-10-02-tactile-identity-confirmation.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../../../modules/sensors.md)；本页保留原过程与证据。

# 2026-10-02：双指逻辑侧与 serial 外部确认

## 勘误对象

此前[零载荷基准记录](2026-10-02-tactile-zero-load-baseline.md)和
[离线重建记录](2026-10-02-tactile-offline-reconstruction.md)正确说明了 bag 本身没有 serial，
但当时 A/B 到物理侧和 serial 的映射尚未确认。本记录追加外部人工确认，不重写旧记录。

## 确认事实

- 右侧夹爪触觉为逻辑 A，厂商 serial `X26040546`。
- 左侧夹爪触觉为逻辑 B，厂商 serial `X26040345`。
- 该身份来自操作者人工确认，不是从 `record010` 消息字段推导。

## 处理结果

`tactile_baseline` metadata 增加每个逻辑侧的 `serial` 与 `physical_side`。重新生成的确认版
基准继续通过五项零载荷检查；离线重建报告继承相同身份。原始无身份版本继续保留在本地，
用于证明数值重建并不依赖 serial。
