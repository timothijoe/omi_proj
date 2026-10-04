# 六关键点自动候选与人工审核

本地工具位于 `src/omi_hil_rl/keypoints/`，独立于 policy、ROS 和机器人控制。
首次样图工作项目已准备在 `local/keypoint_review/six_point_examples/`，包含原图的逐字节副本、来源清单和独立标注文件。

## 启动

从 `omi_proj/` 执行：

```bash
bash scripts/keypoint_review.sh serve --project local/keypoint_review/six_point_examples
```

打开 <http://127.0.0.1:8765>。服务默认只监听本机；退出按 Ctrl+C。
已运行时直接打开页面，不需再次启动。另一个服务进程无法同时写同一项目。

启动脚本使用系统 Python 3 的 NumPy、Pillow、OpenCV，清除 ROS PYTHONPATH 污染。
本机验证版本：Python 3.12、NumPy 1.26.4、Pillow 10.2.0、OpenCV 4.6.0。
没有下载视觉模型，没有上传图片。换机可准备独立 Python 环境安装 `numpy pillow opencv-python-headless`，
然后 `PYTHONPATH=src python -m omi_hil_rl.keypoints.app serve --project ...`。
项目安装方式另提供 `keypoints` extra 和静态资源 package-data；常规标注无需加载 MuJoCo、Torch、厂商 SDK。

## 首次导入其他同格式样例

```bash
bash scripts/keypoint_review.sh init \
  --source /tmp/omi_six_keypoint_handoff_20261004 \
  --project local/keypoint_review/my_new_project
```

源目录必须有 `manifest.json`、`annotation_template.json` 及相对路径图片。
新项目目录必须不存在。导入验证 schema、图片哈希、原尺寸/RGB、重复 ID、路径范围和模板/manifest 一致性。
不同子目录中的同名图片保留完整相对路径，不按 basename 混合。
程序不修改源目录，不读取 manifest 所列 NPZ 内容；NPZ 路径只作为来源记录。

## 正常审核流程

1. 浏览列表或配对视角。默认图片仅128×128，放大不增加信息；相机并非严格同时曝光。
2. 点击“本图生成候选”或“批量生成候选”。虚线轮廓只是几何边界，可能属于外壳或背景。
3. 为每个 episode/view 选择参考图。框选真正的孔口和金属插头区域，填写目标 ID。
   可以先选算法轮廓，再点“将选中轮廓设为孔口参考区”；这不自动确认真实入口。
4. 按物理身份选择六个点名，再点击原图。孔口连接顺序为 TL→TR→BR→BL。
   两个插头点必须是同一金属插入端最前缘的指定角，不能用夹爪或塑料角代替。
   物理身份不随屏幕旋转交换；说明框记录入口圈与基准视角定义。
5. 看不到的点选择 `occluded`、`out_of_frame` 或 `uncertain`，不强迫补坐标。
   六个状态都处理后，勾选定义确认并“以本图建立 / 更新参考”。
   未知点可保留 uncertain；算法不会从不可见参考生成隐藏坐标。
6. 在同组其他图运行预标注。逐点接受或点击/拖动/数值修正，再核对。
   同图模板匹配只是接口检查；界面明确标注，不作为泛化成绩。
7. “整图审核通过”会要求定义已确认、六点无 unlabeled。已审核的非可见点可通过。
8. 导出 JSON 草稿或已审核 NPZ。导出报告显示纳入/跳过图数。

参考区和定义有独立保存按钮；未提交参考草稿时禁止切图，并提供“放弃参考草稿”。
普通点修改使用“保存”或 Ctrl+S；切图会先保存。保存失败保留内存并阻止切图。
页面刷新前有未保存提示。多窗口版本冲突时，先“下载内存草稿”，再刷新读取新版本并人工合并。
不得用刷新直接解决冲突而丢掉修改。

数字键1–6选择点；撤销/重做支持跨保存操作，撤销结果仍需保存。
Shift+拖动平移，滚动查看；Nearest/Bilinear 可切换。
像素中心从0到127；SVG显示边界从−0.5到127.5，通过逆屏幕变换保存原图坐标。
算法重跑只追加 proposals，不覆盖人工 keypoints。更换参考会重置本组整图审核；旧候选需重跑后才能接受。
原图发生变化或被删除时，服务报错，不清空标注。

## 自动算法的实际范围

`ReferencePredictor.predict(image, view, target_config, reference_image)` 是可替换的纯本地后端。

- 没有参考：Canny + 凸四边形轮廓，保留多个候选；所有命名点返回 uncertain。
- 有确认参考：对每个可见参考点取约11×11原始灰度块，在局部±18px搜索；不重新按屏幕坐标排序。
- 归一化模板相似度低于0.82、次峰差小于0.06、参考块弱纹理、越界、孔口交叉或插头点重合时拒绝。
- 候选保存分数、前两峰、拒绝原因、算法版本、参考配置快照和计时。
- 分数是未校准启发式相似度，不是可见性或正确率概率。算法拒绝只返回 uncertain，不推断遮挡原因。
- 未实现视频传播、仿射/尺度追踪、学习检测器、跨视角几何恢复。旋转、尺度变化、遮挡、反光和相似孔可能失败。
- 参考只用于同 episode/view；不跨 bag、不跨 split。没有根据 bag_004 调参或训练模型。

## 文件与导出

`annotations.json` 是信息完整的主文件，保留来源、时间、人工/建议分离、每图修订与全局 audit。
写入采用同目录临时文件、fsync、原子替换；服务进程 flock 和 HTTP revision 防止多写者覆盖。
浏览器用十进制字符串传递超过2^53−1的整数，磁盘保留原始纳秒整数，避免JavaScript损失精度。
服务仅允许本机 Host，写操作需同源会话 token；这不是远程多人部署系统。

离线 CLI（使用同一项目的服务需先退出）：

```bash
bash scripts/keypoint_review.sh predict --project local/keypoint_review/my_new_project
# 可附加 --image-id bag_001_0025_external，仅生成指定图候选
bash scripts/keypoint_review.sh export --project local/keypoint_review/my_new_project --output /tmp/reviewed_points.npz
bash scripts/keypoint_review.sh evaluate --project local/keypoint_review/my_new_project --output /tmp/keypoint_metrics.json
bash scripts/keypoint_review.sh report --project local/keypoint_review/my_new_project --output /tmp/keypoint_report
# 从此前导出的同项目JSON恢复草稿，不能更改图片身份/来源；发生标签变化则需要重新整图审核
bash scripts/keypoint_review.sh import-draft --project local/keypoint_review/my_new_project --input /tmp/unsaved-annotations.json
```

CLI文件导出拒绝覆盖；报告目录要求不存在。网页导出由浏览器下载。
NPZ用 `allow_pickle=False` 读取，包含：

- `points`：float32[N,6,2]；
- `localization_mask`：bool[N,6]，仅已审核图内、已审核且 visible 的点为1；
- `statuses`：Unicode[N,6]；
- `metadata_json`：Unicode JSON，包含原图哈希/来源/split、点名顺序、参考定义和跳过项。

非可见坐标在张量内填0且mask=0；主JSON仍为null。没有COCO导出。
评估按 split/view/点名报告中位误差、p90、PCK@2/@4、接受覆盖/拒绝比例和已知非可见误报。
无人工标签时指标为空；uncertain 不进入“已知遮挡”分母；同图参考匹配排除。
错孔/身份互换依赖界面人工失败标记。耗时是界面累计经过时间，不是严格的有效劳动时长。
没有从零手标对照，不能据此声称节省审核时间。

## 验证与现有产物

2026-10-04：22项针对性Python测试通过。独立Chromium + Playwright实测点击、拖动、撤销/重做、
2倍DPR、缩放/滚动、刷新、参考区域、非可见审核、NPZ下载、切图保存、冲突和失败恢复通过。
Browser插件没有可用连接，因此用本机headless Chromium验证；未连接个人浏览器会话。

```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_keypoint_review.py -q
```

UI回归脚本 `scripts/verify_keypoint_ui.cjs` **只能对独立一次性项目运行**，里面会写合成测试坐标。
首次创建独立项目并在8766启动，配置Playwright路径后运行：

```bash
NODE_PATH=local/keypoint_review/browser_qa/node_modules node scripts/verify_keypoint_ui.cjs http://127.0.0.1:8766
```

本机Playwright 1.58.2仅安装在local；不影响训练环境。
`ui_test_only/`、`browser_qa/qa-only-export.npz` 和测试截图不是人工真值，严禁用于训练。
正式项目 `six_point_examples/` 当前人工标签仍全为unlabeled；12图29个几何候选、0/72命名建议。
这表示定义尚未确认，不是六点检测成功。原始候选报告见 `initial_report/`。
应先人工确认两视角目标与点身份，再审核30–50张有代表性的图，评估错误/覆盖后再扩充。
需要清晰入口、插入遮挡、相似孔、反光、视角/尺度变化与无目标失败例，并保留未用于调参的新episode。
