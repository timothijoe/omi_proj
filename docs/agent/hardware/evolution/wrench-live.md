# 双指wrench实时显示与持久历史

更新日期：2026-10-05。本文件记录当前实现及验证边界，下一轮开发以此为入口。

## 当前功能

2026-10-05新增独立 `real.wrench_live` 和 `scripts/view_wrench_live.sh`。
默认domain13，只订阅现有A/B WrenchStamped及同路径metadata；只发布诊断Image，
不连接SDK或设备、不发布控制动作。操作见[教程](../../../../tutorials/wrench_live.md)。

单线程ROS订阅将每条消息写入samples.jsonl，保存未缩放Fx/Fy/Fz/Tx/Ty/Tz、
header/接收ROS时间及单调相对时间。无效分量保存null并设valid=false，不替换为有效零。
metadata逐条另存，保留厂商新鲜度、同帧、身份、基线与单位声明，不伪造关联帧号。
默认5Hz刷新和flush，正常退出关闭文件；不保证DDS零丢包或掉电最后一批持久化。

实时内存只保留最近15秒，记录文件保留全程。显示四组有符号曲线、数值、模长、
接收频率/年龄，断流及无效不显示当前值。全程PNG采用580个时间箱的逐分量min/max，
保留峰值；两次流式读取限制内存。原JSONL可在不初始化ROS的情况下重新生成全程图。

## 最小比例尺

用户反馈原自动坐标轴随着小波动连续伸缩，难以观察实际变化，因此增加最小显示范围。
这里的scale是曲线纵轴比例尺，不是policy_scale，不缩放接收到的数值。

| 图组 | 参数 | 默认完整跨度 | 默认上下界 |
| --- | --- | ---: | --- |
| Fx/Fy/Fz | `--force-min-span` | 4 | [-2,2] |
| Tx/Ty/Tz | `--torque-min-span` | 1 | [-0.5,0.5] |

每幅图以零为中心。历史窗口中各分量绝对值均未超出边界时，纵轴固定在最小范围；
超出才按2倍档位扩展，避免随每个样本连续改变刻度。例如力图从±2扩展为±4，再为±8。
当较大样本退出实时窗口，范围可以回到较小档位，但不会小于设置的最小跨度。
各指、力/力矩图分别判断范围；未强制两指在超限时共用相同档位。

参数保存进manifest。实时图、停止后的全程图和重新生成历史图共用规则；
重新生成时默认读取会话保存的参数，旧manifest缺字段时用新默认值，也支持显式覆盖。
原始JSONL、六维数值、模长和控制程序不受绘图比例尺影响。
正在运行的旧进程需停止后重启才使用新规则。

## 运行与产物

```bash
bash scripts/view_wrench_live.sh
# 显式设置当前默认比例尺
bash scripts/view_wrench_live.sh --force-min-span 4 --torque-min-span 1
# 仅记录和生成图，不打开RViz
bash scripts/view_wrench_live.sh --no-rviz --duration 60
# 事后重新生成历史图，读取已保存的比例尺参数
bash scripts/view_wrench_live.sh --review-session local/wrench_live/你的会话目录
```

独立新会话目录拒绝覆盖；记录保存在Git忽略的`local/wrench_live`。
核心产物为samples.jsonl、metadata.jsonl、manifest.json、status.json、report.json、
dashboard.png和history.png。转移历史时复制整个会话目录，PNG不能替代原始数据。

## 已完成验证

首版9项测试覆盖双时钟/符号原值、无效与断流、有限窗口不删除完整记录、
全程图短时峰值及空记录。加入比例尺后专项测试为11项通过，新增最小范围稳定性、
超界按档位扩展、历史重建读取保存设置及显式覆盖验证。

| 阶段 | 现场证据 | 会话目录（项目相对路径） |
| --- | --- | --- |
| 首版无GUI约12秒 | A310/B316条，无非有限值，JSONL及PNG生成 | `local/wrench_live/live_acceptance_20261005` |
| 首版RViz约15秒 | A406/B405条，GUI启动/正常退出，全程图生成 | `local/wrench_live/gui_acceptance_20261005` |
| 最小比例尺约6秒 | A140/B142条，无非有限值，实时及全程图生成 | `local/wrench_live/min_scale_acceptance_20261005` |

首版两个会话的JSONL行数与report逐指计数一致，时间顺序及有限值核对通过。
实时/历史PNG及最小比例尺实时PNG已视觉检查，CLI帮助和git diff --check通过。
后续文档整理没有重复运行设备测试。

## 保留问题与下一轮开发边界

来源未标定，不标N/Nm、不用于力控。header/接收年龄不是曝光同步验收；
SDK未提供wrench来源帧号，新鲜度、与触觉三场同帧关系、物理轴向和单位仍待核对。
工具完整记录的是收到的消息，不能宣称发布端零丢包。

此轮已完成实时查看、完整历史保存和最小比例尺；没有把wrench加入当前无关节BC模型，
没有重训模型或启动真机强化学习。若后续接入训练，需要明确版本化观测、有效性mask、
统计归一化及训练/推理一致性。此前HIL-SERL讨论中的真机step/reset、奖励/成功判定、
transition采集、动作执行契约及Actor/Learner连接仍是独立待开发项。
