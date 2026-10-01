"""Plot fixed-seed policy improvement from a simulation training run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw


def plot_progress(progress_path: Path, output_path: Path) -> None:
    records = [json.loads(line) for line in progress_path.read_text().splitlines() if line.strip()]
    if len(records) < 2 or records[0]["step"] != 0:
        raise ValueError("progress file needs initial and final policy audits")
    width, height = 1000, 580
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    margin = 65
    right = width - 35
    top = 55
    bottom = height - 75
    steps = max(1, records[-1]["step"])
    errors = [float(record["mean_final_tcp_error_m"]) for record in records]
    error_max = max(0.05, max(errors) * 1.1)
    x = lambda step: margin + int((right - margin) * step / steps)
    y_success = lambda value: bottom - int((bottom - top) * value)
    y_error = lambda value: bottom - int((bottom - top) * value / error_max)
    draw.line((margin, top, margin, bottom, right, bottom), fill="black", width=2)
    for level in (0.0, 0.5, 1.0):
        yy = y_success(level)
        draw.line((margin, yy, right, yy), fill="#dddddd", width=1)
        draw.text((8, yy - 8), f"{level:.1f}", fill="black")
    draw.line([(x(row["step"]), y_success(float(row["success_rate"]))) for row in records], fill="#148544", width=4)
    draw.line([(x(row["step"]), y_error(float(row["mean_final_tcp_error_m"]))) for row in records], fill="#cc3434", width=4)
    draw.text((margin, 12), "Policy improvement: fixed-seed evaluation without intervention", fill="black")
    draw.text((margin, height - 48), "Green: success rate (0-1)     Red: mean final TCP error (scaled to chart)", fill="black")
    draw.text((right - 150, height - 48), f"steps: {steps}", fill="black")
    draw.text((margin, height - 25), f"initial {records[0]['success_rate']:.2f} -> final {records[-1]['success_rate']:.2f}; "
              f"error {errors[0]:.3f} -> {errors[-1]:.3f} m", fill="black")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("progress", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    plot_progress(args.progress, args.output)


if __name__ == "__main__":
    main()
