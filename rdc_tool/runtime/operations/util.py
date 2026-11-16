"""rd.util.* operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np

from rdc_tool.runtime import coerce, envelope, live_state


async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:


    if action == "diff_images":
        coerce._require(args, "image_a_path", "image_b_path")
        selected = args.get("metrics", ["mse", "max_abs", "psnr"])
        supported = {"mse", "max_abs", "psnr", "ssim"}
        if (not isinstance(selected, list) or not selected
                or any(not isinstance(item, str) or item not in supported for item in selected)):
            return envelope.failure("metrics must be a non-empty list of mse, max_abs, psnr or ssim", code="validation_error")
        try:
            from PIL import Image
        except Exception as exc:
            return envelope.failure(f"Image diff dependencies missing: {exc}", code="image_diff_dependency_unavailable",
                                    category="capability", details={"failure_stage": "load_image_dependency",
                                        "effects_attempted": False, "context_preserved": True})
        with Image.open(str(args["image_a_path"])) as image:
            a = np.asarray(image.convert("RGBA"), dtype="float32") / 255.0
        with Image.open(str(args["image_b_path"])) as image:
            b = np.asarray(image.convert("RGBA"), dtype="float32") / 255.0
        if a.shape != b.shape:
            return envelope.failure("Image shapes differ", code="image_shape_mismatch")
        source_height, source_width = a.shape[:2]
        region = args.get("region")
        if region is not None:
            fields = {"x", "y", "width", "height"}
            if (not isinstance(region, dict) or set(region) != fields
                    or any(type(region[key]) is not int for key in fields)):
                return envelope.failure("region requires integer x/y/width/height", code="invalid_image_region")
            x, y, width, height = (region[key] for key in ("x", "y", "width", "height"))
            if x < 0 or y < 0 or width < 1 or height < 1 or x + width > source_width or y + height > source_height:
                return envelope.failure("region must be nonempty and inside both images; no clamping or resizing", code="invalid_image_region")
            a, b = a[y:y + height, x:x + width], b[y:y + height, x:x + width]
        if "ssim" in selected and min(a.shape[:2]) < 11:
            return envelope.failure("SSIM requires both dimensions to be at least 11 pixels", code="ssim_window_too_large")
        diff = a - b
        mse = float((diff ** 2).mean())
        out = {"identical": bool(np.array_equal(a, b)),
               "source_size": {"width": source_width, "height": source_height},
               "region": region or {"x": 0, "y": 0, "width": source_width, "height": source_height}}
        if "mse" in selected:
            out["mse"] = mse
        if "max_abs" in selected:
            out["max_abs"] = float(abs(diff).max())
        if "psnr" in selected:
            out["psnr"] = float(20 * np.log10(1.0 / np.sqrt(mse))) if mse > 0 else None
            out["psnr_status"] = "infinite" if mse == 0 else "finite"
        if "ssim" in selected:
            # Wang et al. 2004: 11x11 Gaussian, sigma 1.5, population covariance.
            # Average valid windows per RGBA channel; no hidden color conversion.
            kernel = np.exp(-(np.arange(-5, 6, dtype="float64") ** 2) / (2 * 1.5 ** 2))
            kernel /= kernel.sum()

            def average(values):
                height, width = values.shape
                horizontal = sum(weight * values[:, i:i + width - 10] for i, weight in enumerate(kernel))
                return sum(weight * horizontal[i:i + height - 10, :] for i, weight in enumerate(kernel))

            scores = []
            for channel in range(4):
                x, y = a[:, :, channel].astype("float64"), b[:, :, channel].astype("float64")
                mx, my = average(x), average(y)
                vx, vy = np.maximum(average(x * x) - mx * mx, 0), np.maximum(average(y * y) - my * my, 0)
                covariance = average(x * y) - mx * my
                score = ((2 * mx * my + 0.01 ** 2) * (2 * covariance + 0.03 ** 2)
                         / ((mx * mx + my * my + 0.01 ** 2) * (vx + vy + 0.03 ** 2)))
                scores.append(float(score.mean()))
            out["ssim"] = float(np.mean(scores))
            out["ssim_method"] = {"channels": "RGBA", "window": 11, "sigma": 1.5,
                                  "data_range": 1, "covariance": "population", "boundary": "valid"}
        output_path = args.get("output_path")
        if output_path:
            # An alpha difference is data to visualize, never the output opacity.
            absolute = np.abs(diff)
            visible = np.maximum(absolute[:, :, :3], absolute[:, :, 3:4])
            diff_img = (np.clip(visible, 0.0, 1.0) * 255.0).astype("uint8")
            out_path = Path(str(output_path))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(diff_img).save(out_path)
            out["diff_path"] = str(out_path)
            out["diff_visualization"] = "opaque-rgb-absolute-difference-with-alpha-difference-as-gray"
        return envelope.success(metrics=out)


    if action == "list_artifacts":
        prefix = str(args.get("prefix", ""))
        artifacts = live_state._artifact_store.list_artifacts(prefix=prefix)
        projection = envelope._projection_request(args, "rd.util.list_artifacts")
        if projection:
            return envelope.success(
                artifacts=artifacts,
                projections=envelope._artifact_rows_projection(
                    artifacts,
                    include_tsv_text=bool(projection.get("include_tsv_text", False)),
                ),
            )
        return envelope.success(artifacts=artifacts)

    if action == "cleanup_artifacts":
        result = live_state._artifact_store.cleanup_artifacts(
            older_than_ms=args.get("older_than_ms"),
            prefix=str(args.get("prefix", "")),
            max_total_bytes=args.get("max_total_bytes"),
        )
        return envelope.success(**result)

    return envelope.failure(f"Unsupported util action: {action}", code="runtime_error")
