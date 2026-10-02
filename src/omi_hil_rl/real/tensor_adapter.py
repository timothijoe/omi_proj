"""Convert OMI NumPy observations into a batched Torch policy input."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np


IMAGE_KEYS = frozenset({"external_rgb", "wrist_rgb", "tactile_raw", "tactile_depth_delta"})


def observation_to_torch(
    observation: Mapping[str, np.ndarray],
    *,
    device: str = "cpu",
    add_batch_dim: bool = True,
    normalize_uint8: bool = True,
):
    """Return a dict of tensors, converting HWC images to CHW.

    Torch remains an optional training dependency; importing this module does
    not import Torch until this function is called.
    """

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("Torch is required to create network inputs") from exc

    result = {}
    for key, source in observation.items():
        value = np.asarray(source)
        if key in IMAGE_KEYS and value.ndim == 3:
            value = np.moveaxis(value, -1, 0)
        value = np.ascontiguousarray(value)
        tensor = torch.as_tensor(value, device=device)
        if normalize_uint8 and tensor.dtype == torch.uint8:
            tensor = tensor.to(dtype=torch.float32).div_(255.0)
        elif tensor.dtype == torch.float64:
            tensor = tensor.to(dtype=torch.float32)
        if add_batch_dim:
            tensor = tensor.unsqueeze(0)
        result[key] = tensor
    return result
