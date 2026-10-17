# 2026-10-17 SpacePilot 驱动、位姿演示与项目收纳

## 目标与实际实现

用户要求检测 SpacePilot、安装驱动并用可视化操控物体六自由度；随后要求按 `PROMPTS/documentation_organizer.md` 将工具纳入 OMI 文档与代码体系。

现场 USB 检测到 `046d:c629` / 3Dconnexion SpacePilot Pro。安装 Ubuntu `spacenavd 1.2-1`、`libspnav0 1.1-2`；已有 `python3-tk 3.12.3-0ubuntu1`。用户完成系统管理员认证后，服务 active/enabled。

先在工作区独立工具中实现 Python ctypes + libspnav + Tk 的位姿演示，实际收到六轴输入，30 秒探针累计 1366 条运动事件，GUI 显示物体运动。修正高 DPI 下按钮被裁切的布局后，用户试用并提出方向和操作要求。

按反馈加入仅平移/仅旋转/六轴模式、可选单轴优先；从最初只支持键盘数字键补齐实体按键 12/13/14 的模式切换。最终坐标明确为前 +X、左 +Y、上 +Z，并按反馈反转 roll 输入。历史过程中“向前 +Y”的口头理解已被最终坐标要求替代；最新映射只看[当前纪传体](../evolution/spacepilot-pose.md)。

## 项目收纳

- 正式源码纳入 `src/omi_hil_rl/hardware/spacepilot_pose.py`，启动脚本为 `scripts/spacepilot_pose.sh`。
- 默认导出目录调整为 `local/spacepilot/`，增加 `--output-dir`。
- 旧工具源码、README、脚本和当时日志复制到 `local/spacepilot/migration_20261017/`，保存 `source_sha256.json`；原工作区路径改为兼容启动入口，避免维护两份实现。
- 本机桌面应用入口切到项目脚本，项目窗口日志进入 `local/spacepilot/viewer.log`。
- 沿用 hardware 领域，补齐能力纪传体、接口、操作者教程及导航；没有为一次输入方向微调新增架构决定。
- 开始时分支为 `oct_10_branch`，已有 `tutorials/README.md` 修改和未跟踪的 Ubuntu 22.04 教程；保留这些改动。

## 项目内验证证据

| 证据等级 | 本轮结果 |
| --- | --- |
| 文件纳入 | 正式 Python 模块、Shell 启动脚本、专项测试和文档已建立；未拷贝虚拟环境或驱动二进制 |
| 静态/入口 | `bash -n scripts/spacepilot_pose.sh`、`--help`、Python 模块导入通过 |
| 自动测试 | `PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -p test_spacepilot_pose.py -v`：6 项通过 |
| 只读设备 | 新项目入口 `--probe 2` 成功连接 SpacePilot PRO；该轮 motion_events=0、button_events=0 |
| GUI | 新项目脚本已启动桌面窗口；截图与导出复验见本篇追加验证结果 |
| 真机运动 | 未运行；演示没有机器人执行接口 |

专项测试覆盖坐标方向和 roll 修正、模式锁定、单轴选择与滞回、四元数积分/局部坐标、死区及限幅、按下/松开同帧不漏按、超时输入清零。

## 当时限制与后续影响

旧目录的实际运动和用户试用结果属于迁移背景，不能替代项目版本的全部人工验收。项目内实体 1/2/3 三键逐键操作及最终 roll 手感仍需用户确认；模拟事件测试不能证明物理按钮全链路。没有 LCD 应用、长时间运行测试、ROS/机械臂控制或 RL 接管。

这次收纳提供后续接入的输入参考；如接机器人，需要另行定义 Base/Tool 变换、单位、速度/限位、控制权与停止语义，不能把场景位置直接发给控制器。本次未创建本地 commit，未执行 git push。

## 同轮追加：项目 GUI、实体 3 与 JSON 复验

项目窗口截图 `local/spacepilot/migration_20261017/project_viewer.png` 已检查：所有控制项可见，运动事件计数 2244，位置和 RPY 均变化；顶部与单选框显示六轴模式，右下显示「实体 3 · 松开」。项目 `viewer.log` 同时记录 `SpacePilot button 3 (id=14) -> all`。这补充了迁移后的真实输入和实体 3 行为证据；实体 1/2 的物理按键仍未逐键复验。

单独创建 Tk Viewer、指定导出目录并替换文件选择器返回值，实际写出 `export_smoke.json`；核对 XYZ、`wxyz`、RPY、坐标声明和默认目录通过。该检查验证导出代码，不等同文件选择对话框完整人工操作验收。

旧 Shell 和 Python 兼容入口的 `--help` 均通过；`git diff --check` 无错误，迁移备份、日志和生成物由现有 `local/` 忽略规则覆盖。
