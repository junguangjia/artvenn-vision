"""Isolated optional LibRaw conversion; the parent enforces a 60-second deadline."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from .images import MAX_PIXELS, save_preview
from .storage import VisionError, checkpoint, require


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    try:
        try:
            import rawpy
        except ImportError:
            raise VisionError("raw_decoder_not_installed") from None
        with rawpy.imread(str(args.source)) as raw:
            require(
                raw.sizes.raw_width * raw.sizes.raw_height <= MAX_PIXELS,
                "image_pixel_bound_exceeded",
            )
            pixels = raw.postprocess(
                half_size=True,
                use_camera_wb=True,
                use_auto_wb=False,
                output_color=rawpy.ColorSpace.sRGB,
                output_bps=8,
                user_flip=None,
                no_auto_bright=True,
                gamma=(2.222, 4.5),
            )
            image = Image.fromarray(pixels).convert("RGB")
            dimensions = [int(raw.sizes.width), int(raw.sizes.height)]
        processing = save_preview(image, args.target, dimensions)
        processing["recipe"] = "libraw-camera-wb-half-size-bt709-jpeg-1536-v1"
        checkpoint(args.result, {"status": "completed", "processing": processing})
        return 0
    except Exception as error:
        category = str(error) if isinstance(error, VisionError) else "unsupported_or_corrupt_raw"
        checkpoint(args.result, {"status": "failed", "error_category": category})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
