"""Camera originals and literal 128px ROI tiles for the human replay dashboard."""

import numpy as np
from PIL import Image, ImageDraw

from .observation import ObservationConfig, _crop_square_resize_nearest

CAMERA_TOPICS = {
    "head": "/camera/camera/color/image_raw",
    "wrist": "/tj/dm_sensor/camera/color",
}


def prepare_camera(rgb, name, source_ns, received):
    config = ObservationConfig()
    roi = config.external_rgb_roi if name == "head" else config.wrist_rgb_roi
    # Reuse the observation geometry, but retain the existing human viewer's
    # Lanczos interpolation. This image is not the policy's nearest resize.
    _, (left, top, side) = _crop_square_resize_nearest(rgb, roi, (128, 128))
    original = Image.fromarray(rgb)
    clip = original.crop((left, top, left + side, top + side)).resize((128, 128), Image.Resampling.LANCZOS)
    annotated = original.copy()
    ImageDraw.Draw(annotated).rectangle((left, top, left + side - 1, top + side - 1), outline=(45, 220, 90), width=max(2, side // 80))
    annotated.thumbnail((480, 270), Image.Resampling.LANCZOS)
    return dict(original=annotated, clip=clip, roi=(left, top, side),
                source_ns=source_ns, received=received, source_size=original.size)


def camera_panel(samples, now, stale_s=0.5):
    sheet = Image.new("RGB", (640, 740), (18, 20, 24))
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 8), "CAMERAS | original + ROI / 128 x 128 clip", fill="white")
    draw.text((10, 26), "One bag player; sensors sampled asynchronously", fill="white")
    draw.text((10, 44), "Human preview: Lanczos resize | age = wall time since received", fill="white")
    for row, name in enumerate(("head", "wrist")):
        y = 70 + row * 334
        sample = samples.get(name)
        if sample is None:
            draw.text((10, y), f"{name.upper()}: WAITING", fill="orange")
            continue
        age = max(0, now - sample["received"])
        status = "STALE" if age > stale_s else "VALID"
        draw.text((10, y), f"{name.upper()} | {status} age={age:.2f}s source_ns={sample['source_ns']}", fill="orange" if age > stale_s else "white")
        left, top, side = sample["roi"]
        draw.text((10, y + 16), f"source={sample['source_size']} ROI=({left},{top},{side},{side})", fill="white")
        draw.text((10, y + 32), "Original + ROI (fit to panel)", fill="white")
        draw.text((496, y + 32), "128 x 128", fill="white")
        original = sample["original"]
        sheet.paste(original, ((480 - original.width) // 2, y + 46 + (270 - original.height) // 2))
        sheet.paste(sample["clip"], (496, y + 46 + 71))
    return np.asarray(sheet).copy()
