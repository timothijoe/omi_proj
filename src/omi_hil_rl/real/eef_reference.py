"""Named temporary observation/display translation; never an action increment."""
import numpy as np

TEMP_EEF_OFFSET = (-0.062159, -0.171229, 0.000024)
EEF_REFERENCES = ('raw', 'bag-baseline-v1')


def reference_offset(name):
    if name not in EEF_REFERENCES:
        raise ValueError('Unknown EEF reference: '+str(name))
    return np.array(TEMP_EEF_OFFSET if name == 'bag-baseline-v1' else (0.,0.,0.))


def reference_pose(value, name):
    result = np.asarray(value,dtype=float).copy()
    if result.shape != (7,) or not np.isfinite(result).all():
        raise ValueError('Expected finite xyz/xyzw pose')
    result[:3] += reference_offset(name)
    return result
