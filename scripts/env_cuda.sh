# Source from Bash: source scripts/env_cuda.sh
omi_cuda_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -f "$omi_cuda_root/local/cuda-env/bin/activate" ]]; then
    printf 'Missing CUDA environment: %s/local/cuda-env\n' "$omi_cuda_root" >&2
    unset omi_cuda_root
    return 1
fi
source "$omi_cuda_root/local/cuda-env/bin/activate"
unset PYTHONPATH
# Required for deterministic CUDA matrix multiplication in the benchmark.
export CUBLAS_WORKSPACE_CONFIG=:4096:8
unset omi_cuda_root
