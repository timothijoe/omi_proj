# 腕部相机＋触觉：常用命令速查

三个配套教程共同维护：[本页速查](sensor_commands.md) · [腕部相机详解](wrist_camera.md) ·
[触觉详解](tactile_grid_transport.md)。修改默认参数、话题或启动方式时，三处同步核对；
速查只列常用操作，专项页负责参数、数据语义和排障。

## 准备与检查

每个终端先进入项目根目录，示例统一使用domain13。发布和接收机器必须匹配domain。
换机器的依赖见[安装与迁移](machine_transfer_checklist.md)。以下命令不会控制机械臂或自动录包。

```bash
cd /path/to/omi_proj
bash scripts/start_daimon_live.sh tactile --transport network --domain 13 --plan
bash scripts/start_daimon_live.sh camera --image-mode roi --transport network --domain 13 --plan
```

## 两个终端分别采集

```bash
# 终端1：双指24×16数值场，默认deformation、shear、depth
bash scripts/start_daimon_live.sh tactile --transport network --domain 13

# 终端2：腕部ROI图像，128×128
bash scripts/start_daimon_live.sh camera --image-mode roi --transport network --domain 13
```

如需raw或wrench，先Ctrl+C停止终端1，再选择以下**一条**替代命令；腕部不必停止：

```bash
# 额外raw
bash scripts/start_daimon_live.sh tactile --transport network --domain 13 --publish-raw
# 额外六维力/力矩
bash scripts/start_daimon_live.sh tactile --transport network --domain 13 --tactile-wrench
# 两者都要
bash scripts/start_daimon_live.sh tactile --transport network --domain 13 --publish-raw --tactile-wrench
```

腕部改全图：先停止终端2，再运行：

```bash
bash scripts/start_daimon_live.sh camera --image-mode full --transport network --domain 13
```

| 内容 | topic（a/b分别对应两指） | 默认情况 |
| --- | --- | --- |
| 三个触觉场 | `/omi/tactile_grid24x16/{a,b}/{deformation,shear,depth}` | tactile默认发布 |
| 触觉诊断 | `/omi/tactile_grid24x16/{a,b}/{metadata,status}` | 默认发布，建议录制 |
| 触觉raw | `/omi/tactile/{a,b}/raw` | grid需`--publish-raw` |
| 六维力/力矩 | `/omi/tactile_grid24x16/{a,b}/wrench` | 需`--tactile-wrench`，无SDK帧号时标记未同步 |
| 腕部ROI | `/omi/wrist/color/image_roi` | camera需`--image-mode roi` |
| 腕部全图 | `/omi/wrist/color/image_raw` | 与ROI二选一，camera默认full |
| 腕部诊断 | `/omi/wrist/status` | 默认发布 |

花括号是话题表简写，不要原样粘贴给录包工具。raw不在grid前缀下；infer在grid模式仍不发。
SDK单位和坐标轴未标定，wrench有数值不代表已同步或可用于力控。

## 查看和停止

新小矩阵录包（ZIP或MCAP bag目录）：

```bash
bash scripts/view_grid_observation_3d.sh /path/to/bag.zip
```

该入口默认独立domain92，不连接设备，详见[回放教程](grid_bag_review.md)。
当前grid回放器尚不显示可选raw；实时`view`也尚未适配grid数值场。
查看腕部图像可使用[腕部教程](wrist_camera.md)的view命令；不要把触觉WAITING误判为采集失败。
需要完整的旧实时看板，按[旧三终端方案](daimon_live.md#三个终端分别启动本机推荐复制此处)使用显式full触觉。

各采集终端Ctrl+C只停止该组；关闭独立view不停止相机/触觉。更改参数需重启相应采集。
同一传感器不要重复启动，不能把`all`入口叠加到正在运行的分终端采集上。
