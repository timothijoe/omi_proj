# 冻结ResNet-10历史策略实验

结果与实现边界见[实验说明](../docs/agent/training/evolution/resnet10-history.md)。
以下命令从项目根目录执行。训练使用已有v3数据与原004/008验证划分。

## 使用已下载权重重新训练

```bash
source scripts/env.sh
python -m omi_hil_rl.training.eef_bc_resnet \
  --plan local/eef_history/oct03_split2/plan.json \
  --weights local/pretrained/serl_resnet10/backbone.pt \
  --output local/eef_history/oct04_resnet10_run2 \
  --steps 2000 --seed 7
```

输出目录必须不存在。训练按验证归一化MSE保存best.pt，最终步保存last.pt。
每次重新计算冻结特征，缓存不跨实验复用。需要PyTorch和已转换权重，不需要JAX或设备SDK。

```python
from omi_hil_rl.training.eef_bc_resnet import load_resnet_history
model, normalization, checkpoint = load_resnet_history(
    "local/eef_history/oct04_resnet10_run1/best.pt"
)
```

该加载器只用于新离线版本，不能把权重直接交给原在线节点。

## 在新环境恢复官方权重

已有文件无需重复下载。缺失时：

```bash
mkdir -p local/pretrained/serl_resnet10
curl -fL --retry 2 \
  https://github.com/rail-berkeley/serl/releases/download/resnet10/resnet10_params.pkl \
  -o local/pretrained/serl_resnet10/resnet10_params.pkl
python3 -m venv local/resnet10-validation-env
local/resnet10-validation-env/bin/pip install 'jax[cpu]==0.4.35' 'flax==0.10.2'
local/resnet10-validation-env/bin/python scripts/prepare_serl_resnet10.py \
  --source local/pretrained/serl_resnet10/resnet10_params.pkl \
  --reference-repo ../hil_serl_projects/hil-serl \
  --dataset local/datasets/oct3_formal/datasets/bag_001
source scripts/env.sh
python -c "from omi_hil_rl.training.serl_resnet10 import convert_npz; convert_npz('local/pretrained/serl_resnet10/flax_arrays.npz', 'local/pretrained/serl_resnet10/backbone.pt')"
python scripts/verify_serl_resnet10.py local/pretrained/serl_resnet10
```

准备脚本在读取pickle之前验证官方文件固定SHA256；参考仓库版本记录在provenance.json。
应恢复参考commit `c32939bccb65f3b8c43a9f9add3d322d4ab0264a`。
转换拒绝覆盖backbone.pt。完整JAX验证环境版本已保存为权重目录的validation-requirements.txt。

## 曲线与同划分比较

本机系统python3有matplotlib；另一个环境运行时需安装matplotlib和numpy。

```bash
python3 scripts/plot_eef_history.py local/eef_history/oct04_resnet10_run1
python3 scripts/compare_eef_resnet.py \
  --baseline local/eef_history/oct03_split2/history \
  --resnet local/eef_history/oct04_resnet10_run1
```

比较脚本先检查数据哈希、归一化、历史索引和标签一致，再生成comparison.json、
comparison_predictions.npz和comparison_curves.png。验证集参与选择best，不是独立测试。

## CPU推理基准

```bash
source scripts/env.sh
python scripts/benchmark_eef_policy.py \
  --cnn local/eef_history/oct03_split2/history/best.pt \
  --resnet local/eef_history/oct04_resnet10_run1/best.pt \
  --plan local/eef_history/oct03_split2/plan.json \
  --output local/eef_history/oct04_resnet10_run1/inference_latency_repeat.json
```

输出文件须不存在。默认每条路径预热20次、测量300次。包含内存预处理及动作反归一化，
不含ROS或图像解码；ResNet缓存路径为离线基准，不代表在线节点已适配。
