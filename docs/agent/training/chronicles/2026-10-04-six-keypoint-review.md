# 2026-10-04：六关键点本地候选与人工审核闭环

依据 `/tmp/omi_six_keypoint_handoff_20261004/HANDOFF.md`，实现独立Python HTTP后端及SVG网页标注界面。
保留已有未提交工作。正式工具、启动器、测试、教程已进入仓库工作树，未提交Git。

## 功能与证据

- 原始12张128×128 RGB无损拷贝至 `local/keypoint_review/six_point_examples/images/`，源清单与交接也保留。
- schema/哈希/路径/六点状态校验；人工与proposals分离；同episode/view目标参考和确认；
  单图/批量算法；拖动、数值、遮挡/画外/不确定、撤销/重做；JSON/NPZ导出。
- 原子JSON写入、单写进程锁、多窗口revision冲突、异常保留内存与草稿下载；纳秒精度保护。
- 22项Python测试通过；UI回归 `scripts/verify_keypoint_ui.cjs` 通过。
- UI回归真实打开本地Chrome headless，DPR2，1600×1100视口；点击、拖动、缩放8倍与滚动、
  刷新恢复、非可见审核、候选保留人工值、NPZ下载、切图保存、冲突与注入磁盘错误后重试均通过。
- 浏览器导出NPZ为(1,6,2)，mask `[1,0,1,1,1,0]`；非可见坐标为0，JSON为null。
  **该数据来自合成UI测试坐标，不是机器人人工真值。**

## 自动候选结果

第一批未配置真实目标参考，各图几何轮廓数量按交接顺序为：3、1、2、3、3、3、2、2、5、1、3、1，
共29；命名点0/72，全部uncertain。正式人工点保持unlabeled，已审核图0，训练导出空(0,6,2)。
平均检测约0.758ms，OpenCV4.6单线程，128×128；包含内存RGB预处理/轮廓，不含IO/HTTP/绘图，
仅12图单次测量，不是稳态延迟统计。
候选常落在白色外框、背景或其它开口，不能把几何候选计数当USB语义准确率。

合成独特纹理平移(+4,+3)六点均恢复；空白和重复纹理拒绝。这只验证模板匹配/拒绝实现。
真实目标尚未人工确认，无真实PCK/像素误差/误报率或审核省时结果，没有宣称鲁棒检测完成。

## 产物

- 正式项目：`local/keypoint_review/six_point_examples/annotations.json`。
- 候选图与逐图拒绝说明：`initial_report/candidate_contact_sheet.png`、`initial_report/report.json`。
- 无真值评估：`evaluation_initial.json`；空训练导出：`reviewed_initial.npz`。
- 浏览器证据：`local/keypoint_review/browser_qa/`；`ui-report.json`与截图；测试项目`ui_test_only/`。
- `ui_test_only/`、`qa-only-export.npz`均显式标明不可作训练真值。

Browser技能连接发现无可用浏览器后，使用独立Playwright1.58.2和本机Chromium测试。
新增依赖只放local，不改变Torch/ROS。用户还需在界面确认真实目标与点名对应。

## 同日补记：交付确认与独立纪传体归档

用户在本次交付后反馈“我觉得你这个现在弄得很好”，并要求记录工作、单独开纪传体、再写入编年体。
已将[六关键点工具纪传体](../evolution/six-keypoint-review.md)完善为独立专题，集中维护目标、六点物理定义、
可见性/审核规则、候选算法、界面、代码入口、保存/导出契约、证据、产物和后续工作。
训练纪传体/编年索引及当前摘要继续链接该专题，不与历史策略网络实验混写。

交付收尾补充验证：逐点接受候选后来源为`human_accepted_proposal`，整图仍需单独审核；
测试服务退出后重新打开存储，保存的坐标与来源保持。正式服务返回12图，全部72个人工点仍为unlabeled。
浏览器报告 `local/keypoint_review/browser_qa/ui-report.json` 已记录上述检查；
正式界面截图为 `local/keypoint_review/six_point_examples/interface.png`。

用户反馈记作对当前工具的认可，不扩大为真实目标身份确认、真实标注精度或任务成功验收。
本次归档仅修改文档，未重新训练、改动policy或操作机器人；没有新增人工真值。
