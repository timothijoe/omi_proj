# 2026-10-04：实时 policy、RB 仲裁与 SDK 转换接通

用户要求读取 `/tmp/omi-gamepad-control-handoff.md`，接入真实观测 policy、手柄干预和 `sdk-x-forward-z-left`，打印/记录转换前后值，并审计 GT 到真机的语义。用户确认远端接收程序选择左臂、FRAME_BASE=0；无需访问其源码路径。

## 实现

新增 `scripts/run_policy_gamepad.sh` 与 `real/policy_gamepad.py`：默认私有候选话题预览，显式 `--execute` 才启用最终发布。`stack_shadow` 可选发布带原始观测时间戳的 SI 增量候选；要求 strict 时间检查、完整10帧、模型边界及单步速度边界、100 ms有效期。模型独立收包/推理，手柄节点独立10 Hz轮询；由 supervisor 联动退出。

手柄节点沿用 RB 按住接管、松开等待新候选、断连暂停、单次消费等语义。人工和模型只在最终出口共用 SDK wrapper。日志保留网络反归一化原始量、显式缩放量、候选时间戳、仲裁来源和转换后 mm/ABC度。修复旧 gamepad_node 中多余右括号的语法问题，增加入口导入回归。

共享 EEF 临时补偿常量；原始 shadow 保持 raw 默认，集成入口要求明确选择 raw 或 bag-baseline-v1。后者将“实时 EEF 基准补偿 v1”用于模型观测，不改源topic，不在动作上重复相加。

## 转换核对

SDK 源码 `Downloads/oct04/sdk_python/SDK_PYTHON.zip` 中 `fx_tcp_force.py` 和 `docs_1003_delta_IK.md` 明确 ABC、FRAME_BASE平移相加/旋转左乘。GT 的基坐标系旋转向量须先换轴，再转 ABC；旧 axis_test 对后三维是旋转向量的假设已被此证据更新。

新增 `scripts/audit_policy_sdk_gt.py`。对 `local/eef_history/oct03_split2/plan.json` 所列10个数据集、1525条训练/验证样本核对保存GT、固定基平移抵消以及 SDK 更新后的目标位姿：全部通过。最大保存GT差9.102e-10，SDK目标位置误差2.467e-10 m、旋转误差9.324e-10 rad。输出 `local/policy_gamepad/gt_sdk_audit.json`。

这是坐标与数值实现验证。安装方向 preset、SDK UserFrame、EEF/TCP物理点仍需实物确认；固定工具偏移旋转后有杠杆臂效应，不能由固定基平移补偿替代。

## 现场只读预览

checkpoint `local/eef_history/oct04_nojoints_cuda_run1/best.pt`，真实 Xbox 已连接。本轮没有按RB现场切换；RB切换由现有自动测试覆盖，没有真机动作验收。

| 运行 | raw / scale=1 | bag-baseline-v1 / scale=0.1 |
| --- | --- | --- |
| 时长 | 25秒 | 30秒 |
| 推理数 | 225 | 280 |
| 有限输出 | 225 | 280 |
| 完整历史 | 186 | 234 |
| 发布候选 | 0 | 234 |
| 仲裁选择 policy | 0 | 234 |
| GPU推理P95 | 14.45ms | 14.24ms |
| EEF最大标准化偏差约 | 30.66 | 16.49 |

第一组约7 mm原始单步输出超过默认1 mm边界，被拒；第二组显式缩放后通过。第一次GPU warmup约0.42–0.46秒，没有执行该过期动作。缺图/历史不齐时暂停。第二组所有选中日志 `published=false`，234条全部经过指定SDK wrapper，现场ROS图也确认最终话题没有本次程序发布者。

产物：`local/policy_gamepad/oct04_preview_raw/`、`local/policy_gamepad/oct04_preview_baseline_scaled/`。包含参数、逐帧推理、报告和仲裁日志。当前输入仍明显超出训练位姿分布；链路跑通不代表任务策略已在真机有效。

相关测试最终90 passed。操作命令与控制约定见[教程](../../../../tutorials/policy_gamepad.md)。

## 后续：动作倍率与手柄现场排查

用户的 `execute_20261004_230422` 运行完成545次推理、427条候选；625次仲裁采样均RB=false，无human。用户报告按键无效后做了60秒只读检测（没有真机发布）：先捕获axis5右扳机RT及摇杆事件，后于52.135秒捕获RB按钮311，57秒起出现RB同时推动摇杆；内核event23与LinuxGamepad结果一致。用记录的真实输入回放仲裁，23个human状态、13个非零人工动作，即使注入policy候选仍由RB优先。记录 `local/policy_gamepad/gamepad_input_diagnostic.json`。这验证输入及软件仲裁，未重新验收远端人工动作。

动作小的直接原因是显式policy-scale=0.1，不是遗漏反归一化或米转毫米。10秒处网络平移[-0.995569,-0.366431,-0.980632]mm，缩放换轴后[-0.099557,+0.098063,-0.036643]mm。未擅自提高倍率；scale=1仍受默认每步1mm范数上限约束，可能拒绝候选。

增强日志：终端显示手柄连接、RB和按下按钮编号；JSONL保留全部轴与按钮。policy终端额外并排显示反归一化mm/旋转向量度及缩放后数值、候选实际发布标志。相关56项测试及编译检查通过。

## 用户确认：后续统一使用 RB 干预

用户已确认继续使用 **RB（右侧上方肩键，Linux按钮311）**，不改成下方RT扳机。

- 按住RB并推动摇杆：人工接管，覆盖policy候选。
- 按住RB、摇杆居中：人工零增量，policy不接管。
- 松开RB：丢弃旧候选，等待松开之后的新有效policy动作。
- 手柄断开：暂停并输出零增量。

优先级指10 Hz软件仲裁，不能撤销远端已经执行的动作。现场已确认RB和摇杆输入，实际输入回放确认人工优先；远端SDK人工动作效果尚未重新验收。

继续讨论时保留当前配置：预训练无关节checkpoint、CUDA纯推理、不启动RL训练；EEF使用bag-baseline-v1临时补偿；policy-scale=0.1；最终出口使用sdk-x-forward-z-left，远端左臂/FRAME_BASE=0。没有因本次排查提高倍率、修改接管键或重新启动真机发布。EEF/TCP物理对齐仍是遗留问题。

## GT动作幅度统计与发布字段核对

对oct03_split2全部1525条已保存action重新统计（训练1283/验证242，未乘policy_scale）。训练最大平移范数8.021863mm、最大旋转向量范数1.600803°；验证分别7.280581mm、1.876575°。全部样本平移P50/P95/P99为0.824969/3.234648/5.032287mm，旋转角为0.158679/0.640272/0.967323°。六维分量各自绝对最大值为[8.011552,6.621774,5.796310]mm和[1.667708,1.500865,1.059324]°（旋转向量；各列极值不一定来自同一条）。统计文件local/policy_gamepad/gt_action_ranges.json。

当前默认1mm/1°每步执行门限是保守试跑设置，非GT最大值。仅幅度检查，原GT scale=1会拦633/1525条（41.5%），scale=0.5拦266条（17.4%），scale=0.1拦0条；未统计输入时间和历史完整性等其他门控。

最终ROS数据为/omi/action/decision的Float64MultiArray.data，对应selected_actions.jsonl中published=true的command_mm_deg。终端须看仲裁来源policy/human/paused_*且“已发布”的最终mm/ABC度，不以policy_candidate的仅预览值判断实际下发。模型报告action_publishers=[]仅描述模型进程，不代表独立仲裁器没有发布。

## 用户要求：保方向等比例限幅

执行超限行为由“拒绝候选”改为：反归一化 → policy_scale → 平移与旋转向量分别按范数等比例限幅 → 门控 → RB仲裁 → SDK换轴/ABC。只有大于上限才缩小，不放大较小动作。保留平移方向和旋转轴，但两个部分独立缩放会改变相对比例；不逐轴截断，不直接限幅欧拉角。默认仍1mm/1°每步，参数与手柄速度上限一致。仲裁器仍独立检查候选范数，拒绝外部未限幅超限候选。

用户例子scale=0.5后平移17.08315mm、旋转5.13810°；分别再乘0.0585372和0.194625。限幅后平移[-0.053538,0.703002,-0.709170]mm，旋转向量[-0.330253,0.940250,-0.082838]°；SDK预览[-0.053538,0.709170,0.703002,-0.329559,0.085543,0.940007]。最后3维为ABC，其范数不是限幅所用的旋转角。

未缩放预测实验异常边界50mm/0.25rad、非有限值、缺帧、时间与过期检查仍拒绝；RB人工优先不变。日志记录scaled_before_limit_m_rad、translation_limit_scale、rotation_limit_scale、norm_limited，candidate_m_rad为限幅后的值。终端明确显示限幅前后。99项相关测试通过；未启动真机，已有进程需要重启才生效。
