# 六关键点自动预标注与人工审核工具

更新：2026-10-04。本页独立维护工具的功能现状、数据契约、实现与已知限制。
操作步骤见[教程](../../../../tutorials/six_keypoint_review.md)，开发及交付过程见[编年记录](../chronicles/2026-10-04-six-keypoint-review.md)。

## 目标与当前阶段

为USB插接任务的外部、腕部两路128×128 RGB图提供自动候选、人工修正、审核、持久化及导出，
为未来关键点辅助学习准备标签。工具属于独立数据准备环节，不修改现有policy、训练划分、损失或特征缓存，
不启动策略训练或机器人闭环。

已完成本地工具第一版及软件交互验证。用户在交付后认可当前工具，并要求单独维护纪传体及编年记录。
这项反馈不等于目标孔定义已确认、人工标签已完成或真实关键点精度已验收。

## 六点与审核契约

固定点名为 `plug_tip_left`、`plug_tip_right`、`socket_top_left`、`socket_top_right`、
`socket_bottom_left`、`socket_bottom_right`。两插头点属于同一金属插入端的最前缘；四孔口点属于
目标实际入口的同一圈内轮廓。物理身份需在参考图中说明，不随屏幕横纵排序重新命名。
孔口连线顺序为TL→TR→BR→BL；插头只连两点。

目标按episode/view保存对象ID、参考图、插头/孔口ROI、六点参考状态及定义说明。
参考不跨episode/view/split；两视角只作人工辅助，不做未标定三角测量。
当前交接的全局定义版本仍为 `draft-v1-needs-reference-confirmation`，各组实际物理定义由人工确认配置及修订追溯。

每图保留六点，每点有 `unlabeled`、`visible`、`occluded`、`out_of_frame`、`uncertain` 五种状态。
仅visible有原图坐标；其余人工坐标为null。图像放大不改变坐标系，整数像素中心为0至127。
算法拒绝只能说明不确定，不能擅自解释为物理遮挡。

整图通过要求定义已确认、六点均明确处理；遮挡/画外/不确定可作为已审核结果。
修改点或参考会撤销受影响的整图审核；自动生成候选不自动审核，重新运行不覆盖人工标签。

## 自动候选与边界

可替换接口为 `ReferencePredictor.predict(image, view, target_config, reference_image)`。

- 未确认参考：Canny边缘和凸四边形轮廓产生多个几何候选；命名点全部返回uncertain。
- 确认参考后：按参考中的固定点名，对可见点的局部灰度块做模板匹配，不从不可见参考补造坐标。
- 搜索约11×11像素块、局部±18px；相似度低于0.82或次峰差小于0.06时拒绝。
- 弱纹理、越界、孔口交叉/退化、插头点重合也会拒绝；保留分数、前两峰、拒绝原因和参考配置快照。

分数是未校准的相似度，不是正确概率。当前没有学习检测器、视频传播、仿射/尺度跟踪或外部推理服务。
相似孔、背景、反光、旋转、尺度变化及遮挡均可能失败；几何正确不证明语义或可见性正确。

## 界面与实现入口

本地HTTP服务默认监听 `127.0.0.1:8765`。界面包含图片状态筛选、两视角对照、六点表、稳定颜色及点名、
候选叠加、缩放/平移、Nearest/Bilinear、点击/拖动/数值修正、逐点接受、整图审核、撤销/重做及失败标记。
参考表单单独保存，未提交参考草稿时禁止切图；普通标签切图前先保存，失败保留内存并允许下载草稿。

| 入口 | 职责 |
| --- | --- |
| `src/omi_hil_rl/keypoints/storage.py` | schema、哈希/路径校验、修订、锁、原子存取与NPZ |
| `src/omi_hil_rl/keypoints/predict.py` | 几何候选、参考模板匹配与拒绝 |
| `src/omi_hil_rl/keypoints/app.py` | 本地HTTP及init/serve/predict/export/evaluate/import-draft/report CLI |
| `src/omi_hil_rl/keypoints/static/` | SVG标注界面与坐标转换 |
| `src/omi_hil_rl/keypoints/evaluate.py`、`diagnostics.py` | 审核标签评估、候选示例图及报告 |
| `scripts/keypoint_review.sh` | 隔离ROS Python路径的启动器 |
| `tests/test_keypoint_review.py`、`scripts/verify_keypoint_ui.cjs` | 后端及独立浏览器交互回归 |

## 持久化与训练导出

JSON主格式为 `omi.six_keypoints.v1`；人工keypoints与算法proposals分开，保留原图哈希、来源、split、
每图修订、时间、全局audit及算法版本。图片身份/来源不可由编辑器改写。
保存使用临时文件、fsync和原子替换；单服务flock及多窗口revision防止覆盖冲突。
损坏JSON、图片丢失/变化、非法路径/坐标或未知状态会报错，不重建空文件覆盖。

浏览器通过十进制字符串传递超出JavaScript精确整数范围的纳秒时间戳，磁盘保留原始整数。
同项目JSON草稿可重新导入，标签变化后需再次整图审核。

NPZ仅包含定义已确认、整图已审核的图：`points float32[N,6,2]`、`localization_mask bool[N,6]`、
`statuses`及`metadata_json`。只有已审核visible点的mask为1；非可见点填0且mask为0，主JSON仍保留null。
支持未标图草稿导出，训练导出明确报告跳过项；不提供COCO映射。

评估按split/view/点名统计像素误差、PCK@2/@4、接受覆盖/拒绝及已知非可见误报，排除同图参考匹配。
uncertain不算确定遮挡。错目标/身份互换依赖人工失败标记；界面经过时间不代表严格人工劳动时间。

## 已验证证据与资源

2026-10-04的软件证据：22项针对性测试通过；独立Chromium/Playwright实测DPR2、缩放、滚动、点击/拖动、
撤销/重做、保存/刷新、非可见审核、逐点接受、NPZ下载、并发冲突和注入保存错误后的恢复通过。
服务退出后重新打开存储，已保存标签与来源保持。上述测试不构成真实机器人关键点精度证明。

正式样图工作项目为 `local/keypoint_review/six_point_examples/`：12张原始ROI副本、来源清单、主标注、
交接副本、`interface.png`、`initial_report/`、初始评估及空训练导出。
导入图像来自bag_001/002训练、bag_004验证；保留原划分，没有用bag_004拟合模型或调阈值。
首轮有29个几何候选、0/72命名建议；真实目标未确认，人工点仍全为unlabeled。
真实像素误差、PCK、遮挡误报及审核省时收益尚无数据。

合成独特纹理平移(+4,+3)测试恢复6/6坐标，空白及重复纹理拒绝；只证明匹配与拒绝实现。
`local/keypoint_review/ui_test_only/`及`browser_qa/qa-only-export.npz`中的坐标是合成UI测试，不能用于训练。
资源已登记于[本地资源接口](../../interfaces/local-resources.md)及 `manifests/resources.yaml`。

## 后续工作

先在工具中确认实际目标孔、入口圈和两视角的固定物理身份，再审核30–50张代表性图以检验定义一致性。
补充清晰入口、插入遮挡、反光、相似孔、视角/尺度变化和无目标样本；保留未用于调参的新episode。
根据真实覆盖率、定位误差和人工修正负担决定是否需要更强检测器。
关键点辅助损失、视觉层解冻和policy重训属于后续独立工作，本阶段没有实施。
