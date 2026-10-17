# SpacePilot 六自由度物体操控

如需向机器人发送末端增量，使用独立的[SpacePilot 控制入口](spacepilot_control.md)，支持平移/旋转独立 scale；本页 GUI 用途不变。

用 SpacePilot Pro 控制屏幕长方体的位置与姿态，查看六轴输入并导出一个位姿。此入口不控制机械臂。
以下命令从 `omi_proj/` 执行。

## 1. 检查设备和依赖

本机已验证 Ubuntu 24.04 / 系统 Python 3.12；其他系统需重新核对包名和依赖。

```bash
lsusb -d 046d:c629
systemctl status spacenavd --no-pager
bash scripts/spacepilot_pose.sh --help
```

USB 应显示 `3Dconnexion SpacePilot Pro`。换机器且未安装驱动时执行：

```bash
sudo apt-get install spacenavd libspnav0 python3-tk
sudo systemctl enable --now spacenavd
```

## 2. 先检查输入，再开窗口

```bash
bash scripts/spacepilot_pose.sh --probe 10
```

轻推旋钮或短按实体键。预期显示设备名称、轴值或按键状态，末尾 JSON 中 `connected` 为 true、`device` 为 SpacePilot PRO。没有操作时事件计数为 0 是正常的；连接成功与实际收到操作事件是两项检查。

```bash
bash scripts/spacepilot_pose.sh
```

应出现「SpacePilot · 六自由度位姿实验室」，顶部显示已连接设备，默认「仅平移」。窗口需要本地图形桌面；无 DISPLAY 的 SSH 会话使用 probe。

## 3. 方向和模式

| 操作 | 结果 |
| --- | --- |
| 向前推 / 向后拉 | +X / −X |
| 向左推 / 向右推 | +Y / −Y |
| 向上提 / 向下压 | +Z / −Z |
| 倾斜或扭转 | 旋转模式下调整姿态；roll 绕 X，pitch 绕 Y，yaw 绕 Z |
| SpacePilot 实体 1 / 键盘 1 | 仅平移，姿态锁定 |
| SpacePilot 实体 2 / 键盘 2 | 仅旋转，位置锁定 |
| SpacePilot 实体 3 / 键盘 3 | 六轴联动 |
| Space | 暂停 / 继续 |
| R /「物体复位」 | 位置、姿态归零 |

实体键短按即可；键盘快捷键需要先点一下窗口。当前模式显示在画布顶部和右侧按钮。
默认前 +X、左 +Y、上 +Z；普通鼠标拖动只改变观察角度，不改变世界坐标定义。

想平移时保持「仅平移」，即可完全屏蔽倾斜输入。需要精细对齐时勾选「单轴优先」，只响应力度最大的一轴。速度滑块控制每轴速度；死区增大可减少轻触漂移，代价是更大的起动手感阈值。

默认世界坐标操控；勾选「使用物体局部坐标系」后，轴随物体朝向旋转。右侧可以单独反转每一轴；默认已包含前后与 roll 的校正。设置在程序重启后恢复默认。

红/绿/蓝轴分别为 X/Y/Z，实线是物体轴、虚线是世界轴。网格间距 0.25 m。普通鼠标拖动观察视角，滚轮缩放，「恢复默认视角」回到初始观察方向。

## 4. 导出与停止

点击「导出位姿 JSON」，选择文件名，默认放在 `local/spacepilot/`。也可指定默认目录：

```bash
bash scripts/spacepilot_pose.sh --output-dir local/spacepilot/poses
```

JSON 保存米制 XYZ、`wxyz` 四元数和角度制 RPY，始终是世界坐标下的物体位姿，不能直接当作机器人目标。

点窗口关闭按钮退出。probe 到指定秒数自动退出，也可 Ctrl+C。演示退出后系统驱动继续运行。

## 常见问题

- **连接不到驱动**：检查 USB、`systemctl status spacenavd`、系统是否装了 `libspnav0`；窗口会每 2 秒重试。
- **提示 tkinter 不存在**：安装 `python3-tk`，优先使用上面的脚本；若覆盖 `OMI_SPACEPILOT_PYTHON`，对应解释器也必须有 Tk。
- **设备按键无效果**：看右下角是否显示「实体 1/2/3」，用 probe 检查按键事件；当前仅绑定这三个实体键，驱动自定义按键重映射可能改变编号。
- **推旋钮时物体也旋转**：用实体 1 切回仅平移。
- **只沿一条轴移动**：检查是否启用了「单轴优先」。
- **方向与画面不直观**：恢复默认视角并取消局部坐标模式，再按 XYZ 数值核对；不要将视角方向当作世界坐标。

开发与验证边界见[当前能力说明](../docs/agent/hardware/evolution/spacepilot-pose.md)。
