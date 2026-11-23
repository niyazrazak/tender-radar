"""Sharp images of parts of PDF pages, for Claude to read small print.

Claude scales every image down to about 1568 pixels on its long side, so a whole newspaper page
comes out too small for advert tables (it reads "TD" as "T2"). A page cut into four overlapping
quarters, each rendered at twice the size, keeps the print readable. The pages are vector text,
so rendering larger adds real detail.

Rendering uses macOS `sips`, which needs no extra install. Elsewhere `available()` is False and
the caller keeps its whole-page reading.
"""

import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject

SCALE = 2
PART = 0.58  # each quarter covers 58% of the width and height, so an advert on a cut line is whole in one
QUARTERS = {"top-left": (0, 1 - PART), "top-right": (1 - PART, 1 - PART),
            "bottom-left": (0, 0), "bottom-right": (1 - PART, 0)}  # (left, bottom) as page fractions


class PageRenderer:
    @staticmethod
    def available() -> bool:
        return bool(shutil.which("sips"))

    def quarters(self, pdf: bytes, pages: list[int]) -> list[tuple[str, bytes]]:
        """("page5-top-left.jpg", JPEG bytes) for each quarter of each page (numbered from 1)."""
        reader = PdfReader(BytesIO(pdf))
        images = []
        with tempfile.TemporaryDirectory(prefix="tender-radar-pages-") as folder:
            for number in sorted(set(pages)):
                if not 1 <= number <= len(reader.pages):
                    continue
                for name, corner in QUARTERS.items():
                    path = Path(folder) / f"page{number}-{name}"
                    _write_part(reader, number - 1, corner, path.with_suffix(".pdf"))
                    images.append((path.name + ".jpg", _render(path)))
        return images


def _write_part(reader: PdfReader, index: int, corner: tuple[float, float], path: Path):
    """One quarter of a page, moved to the origin and enlarged: sips draws from (0, 0) and ignores offsets."""
    writer = PdfWriter()
    page = writer.add_page(reader.pages[index])
    x0, y0, x1, y1 = (float(value) for value in page.mediabox)
    width, height = (x1 - x0) * PART, (y1 - y0) * PART
    left, bottom = x0 + (x1 - x0) * corner[0], y0 + (y1 - y0) * corner[1]
    page.add_transformation(Transformation().translate(-left, -bottom).scale(SCALE, SCALE))
    box = RectangleObject([0, 0, width * SCALE, height * SCALE])
    page.mediabox = box
    page.cropbox = box
    writer.write(path)


def _render(path: Path) -> bytes:
    """JPEG, not PNG: PNG keeps transparency, which sips fills with black."""
    source, jpeg = path.with_suffix(".pdf"), path.with_suffix(".jpg")
    subprocess.run(
        ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", str(source), "--out", str(jpeg)],
        capture_output=True, check=True, timeout=120,
    )
    return jpeg.read_bytes()
