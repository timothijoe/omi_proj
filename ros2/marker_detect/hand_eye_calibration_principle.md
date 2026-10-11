# 手眼标定原理说明

> 对应脚本：`hand_eye_calibration.py`（D435 + AprilTag 四角板，eye-to-hand）

运行命令见[marker 检测教程](../../tutorials/marker_detect.md)，当前数据流和输出约定见[技术说明](../../docs/marker_detect.md)。

## 1. 要解决的问题

相机（Intel RealSense D435）固定安装在机器人工作空间内，机械臂末端贴有一块
AprilTag 四角板（marker）。系统能直接得到的是：

- 相机测到的：**marker 在相机坐标系下的位姿** `T_cam_board`（由 PnP 解算）
- 机器人给出的：**末端法兰在基座坐标系下的位姿** `T_base_gripper`（TF 或手动输入）

这两个量描述的是同一个东西（板子）的位置，但各自挂在自己的坐标系上，互相之间
差着一个未知的固定变换——相机相对机器人基座的安装位姿：

```
X = T_base_cam   （相机 → 基座）
```

手眼标定就是用若干组同步采集的「机器人位姿 + 相机观测」，把这个 X 解出来。
解出 X 之后，任意时刻都能把相机看到的东西换算到机器人基坐标系：

```
T_base_board = T_base_cam × T_cam_board
               └── 标定结果 ──┘  └─ PnP ─┘
```

## 2. 数学模型：AX = XB

### 2.1 基本约束

板子是**刚性地**固定在机械臂末端的。设板相对末端的安装位姿为 `T_gripper_board`（Z），
它是一个常量。对任意两次采样 i、j，板子在基座系下的位置必须一致：

```
T_base_gripper(i) · Z  =  X · T_cam_board(i)
T_base_gripper(j) · Z  =  X · T_cam_board(j)
```

两式消去 Z（左乘逆、右乘逆后相减）：

```
T_base_gripper(j)⁻¹ · T_base_gripper(i) · X = X · T_cam_board(j) · T_cam_board(i)⁻¹
└────────── A = 相机运动（在基座系看）──────────┘   └─ B = 板的运动（在相机系看）─┘
```

即经典的 **AX = XB** 形式：

- **A**：同一块板，从机器人那侧看它"动"了多少（其实是相机/基座相对关系的体现）
- **B**：同一个机器人，从相机这侧看板子"动"了多少
- **X**：连接两侧坐标系的未知外参

> eye-in-hand（相机装在臂上）推导方式相同，只是 A、B 的角色互换；
> eye-to-hand（本脚本）的关键点：A 要用**两次机器人位姿的相对变换**
> （`T_base_gripper(j)⁻¹ · T_base_gripper(i)`），而不是单次绝对位姿。
> 这也是脚本里求解前把位姿取逆传入的原因（见 §3.2）。

### 2.2 为什么至少要移动两次以上

X 有 6 个自由度（3 平移 + 3 旋转）。AX=XB 中旋转部分只有当相邻两次位姿的
**旋转轴不平行**时才能提供有效约束。所以：

- 至少 3 个以上不同姿态，工程上建议 **15~25 个样本**
- 姿态要**多变**：绕各轴倾斜 15~30°，只平移不旋转是解不出来的
- 平移信息由旋转"带动"，姿态丰富平移才能收敛

## 3. 脚本实现要点

### 3.1 观测端：PnP 求 `T_cam_board`

1. ArUco 检测器（`DICT_APRILTAG_36H11`）在灰度图上找 tag，要求 ≥2 个 tag
2. 每个 tag 的 4 个角点与 `build_board_object_points()` 生成的板坐标系 3D 点
   按 id 配对（板坐标系：几何中心为原点，+x 右、+y 上、+z 垂直板面朝外）
3. `cv2.solvePnP`（ITERATIVE）+ `solvePnPRefineLM` 精化 → `T_cam_board`
4. 彩色图与对应内参 `K`、畸变 `D` 从 RealSense 的 ROS 2 `Image`、`CameraInfo` 话题订阅；PnP 的板角点坐标使用米
5. 若有对齐到彩色图的深度，取 marker 附近的有效深度中值供人工对照。深度表示光轴方向的 Z 值，须与 PnP 的 Z 分量比较，而非与到光学中心的欧氏距离比较；它不参与求解或自动拒绝样本
6. 采集时连续 12 帧平均（平移取中值、旋转 SVD 投影平均）抑制抖动

### 3.2 求解端：`cv2.calibrateHandEye`

脚本把样本转成 OpenCV 要求的输入形式：

```python
R_b2g = [R.T for R, _, _ in samples]          # T_base_gripper 取逆（旋转部分转置）
t_b2g = [-R.T @ t for R, t, _ in samples]     # 平移部分 -Rᵀt
R_t2c / t_t2c: 直接用 T_cam_board 的旋转平移
```

> OpenCV 的 `calibrateHandEye` 输入约定是 gripper2base 的**逆方向**（base→gripper）
> 加上 target2cam，对 eye-in-hand 直接输出 cam2gripper。本脚本是 eye-to-hand，
> 所以传入取逆后的机器人位姿，并对输出结果同时尝试**原值与逆值**两个候选。

对每个候选 X 做求解的方法有四种（全部尝试）：

| 方法 | flag | 特点 |
|------|------|------|
| PARK | `CALIB_HAND_EYE_PARK` | 双四元数法，旋转精度通常最好 |
| TSAI | `CALIB_HAND_EYE_TSAI` | 经典最小二乘，快但对噪声敏感 |
| HORAUD | `CALIB_HAND_EYE_HORAUD` | 正交迭代 |
| DANIILIDIS | `CALIB_HAND_EYE_DANIILIDIS` | 对偶四元数，同时解旋转平移 |

### 3.3 一致性校验：自动挑正确解

AX=XB 的解对"数据方向搞反"这类错误不敏感——四种方法都可能给出一个
数学上自洽但物理上错误的解。脚本用物理约束做后验校验：

若 X 正确，则下式对所有样本都应等于**同一个常量 Z**（板相对末端的安装位姿）：

```
G(i) = T_base_gripper(i)⁻¹ · X · T_cam_board(i)   应当 ≈ 常量
```

把每个样本算出的 G 与中位数样本的 G 比较，统计：

- **平移一致性**（mm）：所有 G 的平移差平均
- **旋转一致性**（deg）：所有 G 的旋转差平均

每个候选解（4 方法 × 正/逆 = 8 个）都打分：`score = 平移误差 + 2 × 旋转误差`，
取最小者输出。**这两个校验值就是标定质量的直接指标**：

| 平移一致性 | 评价 |
|-----------|------|
| < 3 mm | 很好 |
| 3~8 mm | 可用，检查姿态是否足够多样 |
| > 10 mm | 数据有问题（板没贴平 / 位姿输入错 / 尺寸不符），重新采 |

## 4. 实操要求（决定精度上限）

1. **板子要平**：打印后贴在硬平板上再装到末端。板面弯曲直接进入
   `T_cam_board`，是最大的误差源
2. **打印尺寸必须与脚本中的 `BOARDS` 一致**：45/50 mm 外框和 20 mm tag 决定 PnP 尺度；打印缩放会导致距离错误。脚本没有 `--region-mm` 参数
3. **内参要准**：脚本使用彩色 `CameraInfo` 发布的 K、D；需要核对话题是否对应当前彩色图像与分辨率
4. **样本姿态多样**：俯仰/偏航/滚转都要覆盖，见 §2.2
5. **每个采集点机器人与相机都要完全静止**：脚本按 `s` 后会连采 12 帧，
   若期间检测不稳会拒绝该样本
6. **标定后不要动相机和板子**：X 和 Z 都是"当时安装状态"的属性，
   相机挪一下、板子重贴都要重标

## 5. 输出文件

按 `c` 求解后在 `handeye_result/` 下生成（文件名含时间戳）：

| 文件 | 内容 |
|------|------|
| `handeye_result_*.yaml` | `T_base_cam`、`T_cam_base`、`T_gripper_marker`（4×4） |
| `handeye_result_*.json` | 同上 + 所用方法、一致性误差、样本数 |

使用时（把相机观测转到基座系）：

```python
T_base_board = T_base_cam @ T_cam_board   # 板上任意点 → 基坐标系
```

`T_gripper_marker` 是一致性校验顺带估出的板安装位姿，可用于验证：
`T_base_gripper @ T_gripper_marker` 应与 `T_base_board` 在每个样本处一致。

## 6. `--cam-only` 模式

不接机械臂、不输位姿，只跑「ROS 2 彩色图/内参 → AprilTag → PnP」链路。从 `omi_proj/` 执行：

```bash
python3 ros2/marker_detect/hand_eye_calibration.py --cam-only
# SSH 无显示服务：
python3 ros2/marker_detect/hand_eye_calibration.py --cam-only --headless
```

按 `s` 把当前 `T_cam_board`（12 帧平均后）追加保存到
`handeye_result/cam_only_samples.json`，`d` 删上一条，`c` 打印汇总。
无界面模式每秒在终端输出位姿、默认每 2 秒自动保存一次；可用 `--capture-interval` 和 `--max-samples` 调整。用于单独检查相机测距/测姿，或采集与机械臂无关的板位姿数据。深度仅为参考值，真实精度仍需实物测量验证。
