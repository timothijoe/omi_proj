# Frozen copy of OMI's vector renderer from d017387; independent package must not import the stable viewer.
"""Deterministic visualization for dense tactile vector fields.

The numeric HxWx2 field remains the machine input.  This module creates only
an auditable RGB view with fixed sampling, scale, deadband, and clipping.
Coordinates follow image convention: +x points right and +y points down.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import numpy as np


@dataclass(frozen=True)
class VectorRenderStats:
    sampled_vectors: int
    drawn_vectors: int
    clipped_vectors: int
    max_input_magnitude: float

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


def _draw_line(image: np.ndarray, start: tuple[float, float], end: tuple[float, float], color: tuple[int, int, int]) -> None:
    """Rasterize one clipped line segment with integer Bresenham steps."""

    height, width = image.shape[:2]
    x0 = int(round(np.clip(start[0], 0, width - 1)))
    y0 = int(round(np.clip(start[1], 0, height - 1)))
    x1 = int(round(np.clip(end[0], 0, width - 1)))
    y1 = int(round(np.clip(end[1], 0, height - 1)))
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        image[y0, x0] = color
        if x0 == x1 and y0 == y1:
            return
        twice = 2 * error
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy


def render_vector_field(
    field: np.ndarray,
    *,
    background: np.ndarray | None = None,
    step: int = 16,
    scale_px_per_unit: float = 20.0,
    deadband: float = 0.01,
    max_arrow_px: float = 24.0,
    color: tuple[int, int, int] = (0, 255, 0),
    clipped_color: tuple[int, int, int] = (255, 0, 0),
) -> tuple[np.ndarray, VectorRenderStats]:
    """Render an HxWx2 field without per-frame normalization.

    ``field[y, x]`` is ``(dx, dy)``.  Vectors with magnitude at or below the
    fixed ``deadband`` are omitted.  Display lengths use the fixed scale and
    are capped at ``max_arrow_px``; capped arrows use ``clipped_color``.
    """

    vectors = np.asarray(field)
    if vectors.ndim != 3 or vectors.shape[2] != 2 or vectors.shape[0] < 1 or vectors.shape[1] < 1:
        raise ValueError("vector field must have shape HxWx2")
    if not np.issubdtype(vectors.dtype, np.floating):
        raise ValueError("vector field must use a floating dtype")
    if not np.all(np.isfinite(vectors)):
        raise ValueError("vector field contains NaN or Inf")
    if not isinstance(step, int) or step < 1:
        raise ValueError("step must be a positive integer")
    for name, value, allow_zero in (
        ("scale_px_per_unit", scale_px_per_unit, False),
        ("deadband", deadband, True),
        ("max_arrow_px", max_arrow_px, False),
    ):
        if not np.isfinite(value) or value < 0 or (not allow_zero and value == 0):
            relation = "nonnegative" if allow_zero else "positive"
            raise ValueError(f"{name} must be finite and {relation}")

    height, width = vectors.shape[:2]
    if background is None:
        image = np.zeros((height, width, 3), dtype=np.uint8)
    else:
        base = np.asarray(background)
        if base.shape == (height, width):
            if base.dtype != np.uint8:
                raise ValueError("grayscale background must be uint8")
            image = np.repeat(base[..., None], 3, axis=2)
        elif base.shape == (height, width, 3) and base.dtype == np.uint8:
            image = base.copy()
        else:
            raise ValueError("background must be uint8 HxW or HxWx3 matching the field")

    offset = step // 2
    ys = range(offset, height, step)
    xs = range(offset, width, step)
    sampled = 0
    drawn = 0
    clipped = 0
    max_magnitude = 0.0
    for y in ys:
        for x in xs:
            sampled += 1
            dx, dy = map(float, vectors[y, x])
            magnitude = math.hypot(dx, dy)
            max_magnitude = max(max_magnitude, magnitude)
            if magnitude <= deadband:
                continue
            drawn += 1
            display_length = magnitude * scale_px_per_unit
            was_clipped = display_length > max_arrow_px
            if was_clipped:
                display_length = max_arrow_px
                clipped += 1
            ux, uy = dx / magnitude, dy / magnitude
            end = (x + ux * display_length, y + uy * display_length)
            arrow_color = clipped_color if was_clipped else color
            _draw_line(image, (x, y), end, arrow_color)

            head_length = min(6.0, max(2.0, display_length * 0.30))
            back_angle = math.atan2(-uy, -ux)
            for sign in (-1.0, 1.0):
                angle = back_angle + sign * math.radians(28.0)
                head = (
                    end[0] + math.cos(angle) * head_length,
                    end[1] + math.sin(angle) * head_length,
                )
                _draw_line(image, end, head, arrow_color)

    return image, VectorRenderStats(sampled, drawn, clipped, max_magnitude)
