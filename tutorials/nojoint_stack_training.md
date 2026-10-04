# 不使用关节反馈的历史拼接策略：GPU训练

独立版本 `eef-current9stack-no-joints-v1`。双相机、触觉、末端xyz/xyzw与10个固定历史时刻保留；
关节七维在数据归一化前和网络融合时均屏蔽。每个时刻附加固定为0的joint_mask，
checkpoint保存joint_enabled=0。它们是输入配置/有效性标记，不是动作监督标签。
此版本不支持训练后临时启用关节；旧有模型及数据不被覆盖。

## 训练

从项目根目录执行，输出目录必须不存在：

```bash
source scripts/env_cuda.sh
python -m omi_hil_rl.training.eef_bc_stack \
  --plan local/eef_history/oct03_split2/plan.json \
  --weights local/pretrained/serl_resnet10/backbone.pt \
  --output local/eef_history/nojoints_cuda_repeat \
  --steps 2000 --seed 7 --threads 2 --device cuda --joint-mode off
```

CUDA不可用时报错，不退回CPU。FP32、禁用TF32，确定性算法开启。
沿用batch32、历史首层lr1e-4、其他可训练参数lr1e-3，每100步评估，按验证归一化MSE选best。
`--joint-mode required --device cpu`仍是原默认行为。两种模式有不同模型版本与融合层维度。

## 加载与对照

```python
import torch
torch.backends.cuda.matmul.allow_tf32 = False
torch.backends.cudnn.allow_tf32 = False
from omi_hil_rl.training.eef_bc_stack import load_stack_policy
model, norm, checkpoint = load_stack_policy(
    'local/eef_history/oct04_nojoints_cuda_run1/best.pt', device='cuda')
assert checkpoint['config']['joint_enabled'] == 0
```

网络仍接收14维state容器，前7维为无效占位且被网络丢弃，后7维为末端xyz/xyzw；
不需要测得的关节值。额外joint_mask由本版本强制生成为0，不允许调用者开启。
归一化时joint mean=0、std=1；末端与其他统计仅从训练集计算。
原在线ROS节点不支持这个模型，不能直接传给`eef_history_online.sh`。
新增独立[实时影子推理入口](stack_shadow.md)，仅写本地预测文件，不接执行器。

```bash
python3 scripts/compare_nojoint_stack.py \
  --baseline local/eef_history/oct04_current9stack_run2 \
  --run local/eef_history/oct04_nojoints_cuda_run1
```

产物包括best.pt、last.pt、report.json、history.json、history_index.npz、joint_labels.npz、
验证预测与comparison_curves.png。旧v3已经筛选后的1283训练/242验证样本保持原样，
不恢复过去因为缺关节或缺标签而被排除的观测；这不是新的无关节原始ROS数据导出器。
原对照CPU、新实验CUDA，随机采样轨迹与融合层输入数也有变化，不能单独归因于去掉关节。
末端base_link/A_base对应和TCP语义仍未确认，本次不接执行器。

结果见[功能记录](../docs/agent/training/evolution/nojoint-stack.md)。
