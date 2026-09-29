from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from rdc_tool.core import render_service
from rdc_tool.core.errors import RuntimeToolError


class TextureExportMetadataTests(unittest.TestCase):
    def _save_png(self, output_path: Path, *, valid: bool):
        class Controller:
            def SetFrameEvent(self, event_id: int, force: bool) -> None:
                assert (event_id, force) == (1248, True)

            def SaveTexture(self, save_data, path: str) -> bool:
                assert save_data.resourceId == "texture"
                if valid:
                    Image.new("RGB", (7, 3)).save(path, format="PNG")
                else:
                    Path(path).write_bytes(b"not-a-png")
                return True

        manager = SimpleNamespace(get_controller=lambda session_id: Controller())
        fake_rd = SimpleNamespace(
            TextureSave=lambda: SimpleNamespace(
                resourceId=None, destType=None, mip=0,
                slice=SimpleNamespace(sliceIndex=0),
                sample=SimpleNamespace(sampleIndex=0),
            ),
            FileType=SimpleNamespace(PNG="png"),
        )
        with patch.object(render_service, "_get_rd", return_value=fake_rd):
            return asyncio.run(render_service.RenderService().save_texture_file(
                "session", 1248, "texture", manager, None,
                output_format="png", output_path=str(output_path),
                subresource={"mip": 0, "slice": 0, "sample": 0},
            ))

    def test_reports_actual_saved_image_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "export.png"
            artifact, meta, saved_path = self._save_png(output_path, valid=True)
            self.assertIsNone(artifact)
            self.assertEqual(saved_path, str(output_path))
            self.assertEqual(meta["export_method"], "SaveTexture")
            self.assertEqual((meta["image_width"], meta["image_height"]), (7, 3))

    def test_rejects_unreadable_image_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeToolError, "pixel dimensions could not be read"):
                self._save_png(Path(directory) / "export.png", valid=False)


if __name__ == "__main__":
    unittest.main()
