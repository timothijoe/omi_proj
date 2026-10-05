# 只读触觉阈值预警

```bash
bash scripts/watch_tactile_warning.sh --force-limit 5 --torque-limit 1
```

## 这条命令的阈值和判定关系

- `--force-limit 5`：力模长阈值为 **5**，不是单独的 Fx、Fy 或 Fz 阈值。
- `--torque-limit 1`：力矩模长阈值为 **1**，不是单独的 Tx、Ty 或 Tz 阈值。

A、B 两根手指分别计算，完整报警条件为：

```text
A指力模长 >= 5
或 A指力矩模长 >= 1
或 B指力模长 >= 5
或 B指力矩模长 >= 1
→ 输出 WARNING 日志
```

任意一根手指满足任意一项即可报警，不需要两个手指同时超限，也不需要力与力矩同时超限。
达到阈值（等于）也会报警。负分量同样计入模长，例如 `Fx=-3、Fy=-4、Fz=0`，
力模长为 `sqrt(9+16)=5`，因此触发力报警。

上述 `5 / 1` 只是可替换的示例参数，不是经过验证的安全阈值。
数值为未标定 SDK 单位，**不能直接理解为 5 N / 1 N·m**。

## 输入和计算方式

默认 domain 13，订阅 `/omi/tactile_grid24x16/a/wrench` 和 `b/wrench`。
只读取两根手指的六维力/力矩，不读取模型输出或手柄动作。
程序不启动传感器，也不连接 SDK，不发布动作、不调用保护服务、不改变手柄/接收端配置。
需要已有传感器发布进程；机械臂和手柄由操作员自行启动。

程序直接计算每根手指的原始示数：

```text
|F| = sqrt(Fx² + Fy² + Fz²)
|T| = sqrt(Tx² + Ty² + Tz²)
每根手指：|F| >= force-limit 或 |T| >= torque-limit → WARNING 日志
```

不扣除夹持基线，不要求基线采集，不锁定，不需要复位。数值回落后不再打印超限日志。
夹持预载也计入比较，所以不能直接沿用相对基线保护的阈值。数值为未标定 SDK 单位，
不能当成已经验证的 N、N·m。无效值也会打印 WARNING。

默认每根手指每秒最多打印一次超限日志，首条立即打印。日志包含时间、手指、超限项、
阈值以及原始六分量。此脚本只负责收到示数后的比较，不提供断流看门狗或设备新鲜度证明。

可只监测力或力矩，至少指定一种阈值：

```bash
bash scripts/watch_tactile_warning.sh --force-limit 5
bash scripts/watch_tactile_warning.sh --torque-limit 1
```

提高日志输出频率、同时保存文件：

```bash
bash scripts/watch_tactile_warning.sh --force-limit 5 --torque-limit 1 \
  --log-interval 0.2 --log-file tactile-warning.log
```

文件同名已存在会拒绝覆盖，换新文件名即可。父目录需存在。
`Ctrl+C` 退出。`ROS_DOMAIN_ID=...` 可改变 domain；`--topic-a/--topic-b` 可指定其他 wrench 话题。
运行这个程序不会关闭已经运行的其他保护逻辑；它自身没有拦截能力。

14 项专项测试通过，仅运行了离线测试与 CLI 帮助检查，未代用户启动监听或运动。
