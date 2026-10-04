# 2026-10-04：独立 CUDA 环境与策略推理时延对照

## 结论

用户要求建立 CUDA 环境，测试能否降低现有策略推理时延。已完成环境安装、真实输入测速和数值核验，原 CPU 环境保留。
当前帧独立＋过去9帧通道拼接模型，平均时延由27.741 ms降至7.224 ms，约3.84倍加速；CUDA P95为9.147 ms。

## 环境与方法

- 独立环境：`local/cuda-env/`；激活：`source scripts/env_cuda.sh`。
- Python 3.12、PyTorch 2.14.0+cu130、CUDA runtime 13.0；RTX 5060 Laptop GPU 8GB，驱动595.84。
- 正式CPU/GPU对照使用同一新环境；原 `.venv` 的CPU版2.14.1另作复测，没有被替换。
- 使用既有best权重和32个完整验证窗口，不重新训练；每条路径预热20次、计时300次，随机交错。
- batch1、FP32、CPU2线程、interop1、确定性算法；关闭TF32和cuDNN benchmark。
- 计时包括CPU输入归一化、张量构造、GPU传输、模型前向、结果回CPU与动作反归一化；GPU计时前后同步。

## 结果

| 策略路径 | CPU平均（ms） | CUDA平均（ms） | CUDA P95（ms） |
|---|---:|---:|---:|
| CNN＋GRU，历史特征缓存 | 0.814 | 1.170 | 1.327 |
| ResNet10＋GRU，历史特征缓存 | 10.130 | 3.884 | 4.541 |
| 当前帧独立＋历史通道拼接 | 27.741 | 7.224 | 9.147 |
| ResNet10＋GRU，全窗口重算 | 87.159 | 5.661 | 6.793 |
| CNN＋GRU，全窗口重算 | 2.510 | 1.818 | 2.204 |

小CNN的缓存路径在GPU上略慢；GPU收益取决于实际计算规模及调用、传输开销。

## 验证与边界

三个模型均通过32窗口CPU/GPU预测一致性检查；GRU缓存与完整重算输出也通过检查。
当前拼接模型最大归一化输出差8.5831e-6，最大平移分量差9.5766e-9 m、旋转分量差1.6202e-8 rad。
原CPU环境和新环境各通过9项ResNet/stack测试，依赖检查 `pip check` 通过。

不含相机曝光、图像解码、ROI、ROS传输、对齐和执行，因此不代表端到端闭环时延。
显卡与桌面、播放器等应用共用，没有锁频或停止用户进程；短时计时不能保证实时最坏上界。
未重训、未使用半精度或编译优化，未修改模型架构、未接入在线节点、未控制真机。
后续优先测端到端图像帧龄、命令延迟及持续运行的尾部时延。

## 产物与复现

产物目录：`local/eef_history/oct04_cuda_benchmark/`。

- `cpu_same_env.json`、`cuda.json`：正式同版本对照，含逐次计时、权重/样本哈希、窗口索引、数值差异。
- `cpu.json`：原2.14.1 CPU环境的复测。
- `requirements.txt`、`nvidia-smi-before.txt`、`nvidia-smi-after.txt`：环境记录。
- `run.sh`：复测入口，输出路径须尚不存在。

```bash
bash local/eef_history/oct04_cuda_benchmark/run.sh cuda local/eef_history/oct04_cuda_benchmark/cuda_repeat.json
bash local/eef_history/oct04_cuda_benchmark/run.sh cpu local/eef_history/oct04_cuda_benchmark/cpu_repeat.json
```

完整实验配置见[当前帧与历史拼接实验](../evolution/current-stack-history.md#2026-10-04-cuda-推理对照)，环境与操作见[教程](../../../tutorials/current_stack_history.md#独立cuda环境与复测)。
