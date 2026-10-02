# SDK 原生数值看板

独立包实现：`omi_sensors.dashboard`、`dashboard_launcher`、`dashboard_vectors`。
入口：`scripts/view_sdk_observation.sh`；安装后 `omi-sdk-view`。操作见
[教程](../../../../tutorials/sdk_native_dashboard.md)。

## 边界与数据流

ROS Image/CameraInfo/String/WrenchStamped → 独立消息解码与有界同stamp缓存 → schema2验证 →
单指完整快照 → 固定参数箭头与相机面板 → `/omi/sdk/dashboard` + `/omi/sdk/dashboard_status`。
不导入dmrobotics，不使用FieldProcessor，不调用旧看板、RL observation或机械臂接口。
默认domain88区别于旧稳定入口87；输出topic也独立。用户显式配置同域时仍可能混流，启动提示风险。

订阅sensor QoS best-effort/depth8，兼容reliable和best-effort生产者；输出reliable/depth1，
启动器使用异步FastDDS发布。CameraInfo按时间与尺寸匹配，不将错帧内参标为匹配。
A/B每指核心raw/infer/deformation/shear/metadata精确同stamp匹配；每指最多8个待配帧，
完整快照核心字段不可被重复包替换。数组复制、颜色BGR/BGRA转换、行padding、大小端和有限值检查。
schema1重建元数据和未知来源被拒绝；synthetic可用于无设备验收，但明确标色，不冒充SDK数据。

UI为1536×1000RGB。相机原图与128ROI预览、内参；双指各四列raw/infer/def/shear；
来源、fid、shape、数值范围、基准、时间类型、设备状态、接收年龄/FPS。可选depth/wrench只显示数值摘要。
缺少这些可选字段不阻止核心快照；没有腕部面板、深度热图和力历史曲线。
原始SDK单位保留，不称力场；固定截断红色只表示显示长度超限。

`dashboard_vectors.py` 为原OMI renderer的冻结副本，不修改原文件；保持逐像素等价的回归测试。
这样独立包无需导入带Gym依赖的主RL包，也不会改变稳定viewer行为。

## 状态与限制

单调接收时钟控制STALE，不使用bag历史时间与当前墙钟做差；循环回退重置配帧缓存。
JSON诊断保留reject计数、完整帧数量、pending、epoch、设备状态和CameraInfo匹配状态。
同stamp只证明协议配帧，不证明厂商曝光同步/物理标定；A/B/相机没有跨传感器逐帧同步。
录包入口预检只查topic类型/数量，字段schema在接收时继续检查。

本机Jazzy headless验收覆盖合成源、录包、STALE、循环回放和停止；PNG已检查。
Humble兼容性目标及CI矩阵保留（Pillow9.0兼容处理），未宣称Humble或真SDK设备验收。
本功能只完成可视化，ROS→RL新版profile仍未实现。
本机验证的详细数字、PNG与日志定位见[实现编年](../chronicles/2026-10-02-sdk-native-dashboard.md)。
