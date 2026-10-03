"""Opt-in numeric transport grid; dimensions in names are width x height."""
import numpy as np

MODES = ('full', 'grid24x16')


def topic_root(mode):
    if mode not in MODES:
        raise ValueError('unknown tactile mode: ' + str(mode))
    return '/omi/tactile' if mode == 'full' else '/omi/tactile_grid24x16'


def block_mean(array, channels=2):
    value = np.asarray(array)
    expected = (288, 384, channels) if channels else (288, 384)
    if value.shape != expected or value.dtype.kind != 'f' or not np.isfinite(value).all():
        raise ValueError('grid24x16 requires finite floating point field of shape ' + str(expected))
    value = value.astype(np.float32, copy=False)
    shape = (16, 18, 24, 16) + ((channels,) if channels else ())
    result = value.reshape(shape).mean(axis=(1, 3), dtype=np.float32)
    if not np.isfinite(result).all():
        raise ValueError('nonfinite grid24x16 reduction')
    return np.ascontiguousarray(result)


def prepare_fields(arrays, mode):
    """Full mode is an identity. Grid omits images, preserving optional wrench."""
    topic_root(mode)
    if mode == 'full':
        return arrays, {}
    fields = {key: block_mean(arrays[key]) for key in ('deformation', 'shear')}
    if 'depth' in arrays:
        fields['depth'] = block_mean(arrays['depth'], channels=0)
    if 'wrench' in arrays:
        fields['wrench'] = arrays['wrench']
    return fields, {
        'schema_version': 3,
        'transport_mode': mode,
        'processing_version': 'vendor-flux-block-mean-24x16-v1',
        'resampling': {
            'version': 'block-mean-v1', 'source_hw': [288, 384], 'output_hw': [16, 24],
            'block_hw': [18, 16], 'method': 'area_mean', 'vector_scale': 1.0,
            'source_pixel_center_yx': [8.5, 7.5], 'source_pixel_stride_yx': [18, 16],
        },
        'omitted_fields': [key for key in ('raw', 'infer') if key in arrays],
    }
