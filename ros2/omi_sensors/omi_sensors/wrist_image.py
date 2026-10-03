"""Versioned wrist publication modes; no display labels burned into pixels."""
import numpy as np

TOPICS = {'full': '/omi/wrist/color/image_raw', 'roi': '/omi/wrist/color/image_roi'}
LABELS = {'full': 'Wrist LIVE [FULL original]', 'roi': 'Wrist LIVE [ROI 128x128]'}


def prepare_image(image, mode):
    if mode not in TOPICS:
        raise ValueError('image mode must be full or roi')
    value = np.asarray(image)
    if value.ndim != 3 or value.shape[2] != 3 or value.dtype != np.uint8 or min(value.shape[:2]) < 1:
        raise ValueError('expected nonempty uint8 BGR image')
    height, width = value.shape[:2]
    metadata = dict(image_mode=mode, image_topic=TOPICS[mode], encoding='bgr8',
                    source_size_wh=[width, height], label=LABELS[mode])
    if mode == 'roi':
        side = max(1, round(min(width, height)*.36))
        left = max(0, min(width-side, round(width*.500)-side//2))
        top = max(0, min(height-side, round(height*.704)-side//2))
        crop = value[top:top+side, left:left+side]
        # Exact existing policy contract, not OpenCV INTER_NEAREST's indexing.
        indices = np.rint(np.linspace(0, side-1, 128)).astype(int)
        value = crop[indices[:, None], indices[None, :]]
        metadata.update(roi_xywh=[left, top, side, side],
                        roi_normalized=[.500, .704, .36],
                        processing_version='wrist-roi-v1-nearest-linspace-128',
                        resize='nearest_rint_linspace')
    else:
        metadata.update(roi_xywh=None, processing_version='wrist-full-v1', resize='none')
    metadata['output_size_wh'] = [value.shape[1], value.shape[0]]
    return value, metadata
