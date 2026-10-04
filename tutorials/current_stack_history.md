# 当前帧独立＋过去9帧通道拼接

这是独立离线模型：当前帧为RGB3，过去9帧按从旧到新的顺序拼成RGB27，去掉GRU。
完整配置和结果见[实验说明](../docs/agent/training/evolution/current-stack-history.md)。

## 训练

沿用已经转换的v3数据、oct03_split2划分与SERL预训练权重。项目根目录执行：

```bash
source scripts/env.sh
python -m omi_hil_rl.training.eef_bc_stack \
  --plan local/eef_history/oct03_split2/plan.json \
  --weights local/pretrained/serl_resnet10/backbone.pt \
  --output local/eef_history/oct04_current9stack_repeat \
  --steps 2000 --seed 7 --threads 12
```

输出目录必须不存在。历史首层lr=0.0001，其余可训练参数lr=0.001；batch32。
只缓存冻结的当前帧图像特征，历史首层与其后计算每次更新都重算。
每100步评估完整训练集/验证集，以验证归一化MSE选择best.pt；last.pt保存最终步。
线程数写入配置。全模型仍在CPU训练，未改项目PyTorch安装。

```python
from omi_hil_rl.training.eef_bc_stack import load_stack_policy
model, normalization, checkpoint = load_stack_policy(
    "local/eef_history/oct04_current9stack_run2/best.pt"
)
```

新版本为`eef-current9stack-resnet10-v1`，不能交给既有GRU在线加载器。

## 完成后比较

```bash
python3 scripts/compare_eef_stack.py \
  --cnn local/eef_history/oct03_split2/history \
  --gru local/eef_history/oct04_resnet10_run1 \
  --stack local/eef_history/oct04_current9stack_run2
source scripts/env.sh
python scripts/benchmark_eef_policy.py \
  --cnn local/eef_history/oct03_split2/history/best.pt \
  --resnet local/eef_history/oct04_resnet10_run1/best.pt \
  --stack local/eef_history/oct04_current9stack_run2/best.pt \
  --plan local/eef_history/oct03_split2/plan.json \
  --output local/eef_history/oct04_current9stack_run2/inference_latency_repeat.json
```

绘图使用含numpy/matplotlib的环境，本机为系统python3。
benchmark输出须不存在；CPU固定2线程，包含内存归一化/模型前向/动作反归一化，
不含ROS、图像解码、ROI、设备采集。新模型每次完整计算当前和历史视觉分支，
没有预缓存当前图像；GRU模型同时测整窗重算和复用过去9帧特征两种路径。
