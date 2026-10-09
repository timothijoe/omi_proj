# 当前帧独立＋过去9帧通道拼接

2026-10-09：`local/datasets` 外置后通过原路径软链接读取，重训须挂载移动盘；
本页 `local/eef_history` 权重、计划和输出仍保留本机。见[存储教程](local_data_storage.md)。

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
线程数写入配置。默认仍在CPU训练；新增`--device cuda`与独立无关节版本，见[GPU无关节训练](nojoint_stack_training.md)。原CPU环境不变。

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

## 独立CUDA环境与复测

已安装环境位于 `local/cuda-env`，原CPU `.venv` 不受影响。

```bash
source scripts/env_cuda.sh
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name())"
bash local/eef_history/oct04_cuda_benchmark/run.sh cuda local/eef_history/oct04_cuda_benchmark/cuda_repeat.json
bash local/eef_history/oct04_cuda_benchmark/run.sh cpu local/eef_history/oct04_cuda_benchmark/cpu_repeat.json
```

输出文件必须不存在。`scripts/benchmark_eef_policy.py --device cuda`选择GPU，默认仍为CPU。
需在启动Python前设置`CUBLAS_WORKSPACE_CONFIG=:4096:8`（env_cuda.sh已设置），用于确定性计算。
环境版本锁定记录：`local/eef_history/oct04_cuda_benchmark/requirements.txt`。
新机器可先建立独立venv、安装`torch==2.14.0`的CUDA发行版，再安装项目和版本清单中的依赖；
requirements里的editable项目绝对路径需要按本机调整。安装后必须确认`torch.cuda.is_available()`，
不能仅凭驱动工具显示CUDA版本判断PyTorch可用。运行`pip check`验证依赖。

该环境和脚本仅完成离线CPU/GPU测速；没有替换在线节点的环境或修改模型架构。
