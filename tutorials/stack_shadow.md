# 无关节模型：实时 ROS 影子推理

此入口加载 `eef-current9stack-no-joints-v1`，在 GPU 上读取现场观测进行推理。
不创建动作发布者、不启动驱动、不发送机器人命令；预测只写到本地文件。
末端与模型尚未完全对齐，此入口不能用于确认机器人执行效果。

## 运行

从项目根目录执行，输出目录必须是新目录：

```bash
bash scripts/run_stack_shadow.sh \
  --checkpoint local/eef_history/oct04_nojoints_cuda_run1/best.pt \
  --output local/stack_shadow/my_strict_run \
  --duration 60 --device cuda
```

默认 domain 13；可用 `OMI_SHADOW_DOMAIN_ID` 修改。
使用 `local/cuda-env` 的 PyTorch 与系统 ROS Jazzy；CUDA 不可用会报错，不自动退回 CPU。
`--device cpu` 可显式使用 CPU。程序在指定时长后退出，Ctrl+C 可提前结束并保存报告。
不需要 `marvin_msgs`：此 checkpoint 的关节输入固定禁用。

## 输入与处理

| 输入话题 | 处理 |
| --- | --- |
| `/camera/camera/color/image_raw` | 训练同款 ROI `[.507,.426,.40]`、nearest resize 至 RGB 128×128 |
| `/omi/wrist/color/image_roi` | 已裁剪 128×128，只做颜色/通道布局处理，不重复裁剪 |
| `/omi/tactile_grid24x16/{a,b}/{deformation,shear,depth}` | 各指 2+2+1 通道，合为 10×16×24，不重复池化 |
| `/tj/info/eef_left` | 要求 `base_link`，按训练规则验证并规范化 xyz/xyzw |

使用 checkpoint 内归一化参数；state 前7维为明确禁用的零占位，后7维为 EEF。
本次 checkpoint 腕部相机为 optional：缺失时零图加 mask=0，报告 camera_mask，不能冒充双相机齐全。
不使用关节反馈、wrench 或 RViz 模型计算的 L7 位置来替代 EEF。

按接收时刻在 100ms 网格上选取因果观测，保持当前+过去9个固定槽位。
缺失历史有 mask，不压缩时间、不用未来消息补过去；缺少当前必要输入时不做推理。
收包线程独立于 GPU 推理；错过的决策时刻跳过，不补发过期决策。

## 时间检查和诊断模式

默认 `--header-mode strict` 沿用训练数据入口检查：EEF 源 header 最多旧50ms，其余250ms，最多超前100ms。
接收时间的新鲜度也分别要求50ms/250ms。跨机器时钟偏差会影响源header检查。
解码失败或时间检查失败会清除该路旧样本，避免继续使用旧值。

仅为确认张量和模型能否计算，可显式运行：

```bash
bash scripts/run_stack_shadow.sh \
  --checkpoint local/eef_history/oct04_nojoints_cuda_run1/best.pt \
  --output local/stack_shadow/my_diagnostic_run \
  --duration 60 --device cuda \
  --header-mode receive-only-diagnostic
```

该模式只跳过源 header 年龄检查，仍检查接收新鲜度、数据形状、有限值、四元数和 EEF frame。
原 header 年龄保留在日志，`training_header_guards_enforced=false`；这不代表满足原训练契约。
两种模式均固定 `execution_allowed=false`。不修改系统时钟，不估计或应用时钟偏移。

## 输出与判读

- `manifest.json`：checkpoint 路径/hash、模型版本、输入话题、契约、设备、模式。
- `predictions.jsonl`：逐次决策、缺失原因、历史/camera mask、接收年龄、EEF位姿、预测动作与耗时。
- `status.json`：最新一次决策。
- `first_window.npz`：第一份可推理的真实窗口和预测；若一直缺必要输入则不存在。
- `report.json`：消息接收/接受/拒绝数、推理次数、完整窗口次数、有限输出数和耗时分位数。

预测顺序 `dx,dy,dz,rx,ry,rz`，单位 m/rad，为训练的100ms未来EEF变化代理，不是机器人控制指令。
`within_experimental_bounds` 仅比较原实验增量阈值（平移范数0.05m、旋转范数0.25rad），不代表执行安全。
`deadline_met` 检查计算完成是否还在参考时刻后的100ms周期内。
`inference_ms` 包括归一化、设备传输、forward和输出反归一化；不含曝光、ROS传输和解码，不是端到端延迟。
`eef_max_abs_z` 是输入EEF相对训练集均值/标准差的最大偏离，仅供分布偏移检查，不是模型置信度。

推理数为0时程序返回退出码2，并保留报告；应先查看缺失及拒绝原因，不能仅凭模型加载成功宣称实时推理已跑通。
