#!/usr/bin/env python3
"""Cut Herbert's five portraits from the character reference sheet (1536x1024, outside the repository).
Usage: python3 tools/cut_herbert.py "Herbert Character Comms Reference.png"
Needs ImageMagick (magick). Writes assets/herbert-<face>.bmp.gz: 224x168, 24-bit BMP, gzipped."""
import gzip
import subprocess
import sys
import tempfile
from pathlib import Path

SIZE = (224, 168)
# The "EXPRESSIONS (LINE ART)" tiles on the sheet: face -> (x, y, w, h), inside each tile's rounded border, above its label.
BOXES = {
    'smiling':  (44, 529, 176, 132),
    'serious':  (250, 529, 172, 129),
    'amused':   (452, 529, 164, 123),
    'thinking': (645, 529, 158, 118),
    'speaking': (832, 529, 152, 114),
}


def cut(sheet, out):
    out.mkdir(parents=True, exist_ok=True)
    for face, (x, y, w, h) in BOXES.items():
        with tempfile.TemporaryDirectory() as tmp:
            bmp = Path(tmp)/f'{face}.bmp'
            subprocess.run(['magick', str(sheet), '-crop', f'{w}x{h}+{x}+{y}', '+repage', '-filter', 'Lanczos',
                            '-resize', f'{SIZE[0]}x{SIZE[1]}!', f'BMP3:{bmp}'], check=True)
            (out/f'herbert-{face}.bmp.gz').write_bytes(gzip.compress(bmp.read_bytes(), 9, mtime=0))


if __name__ == '__main__':
    if len(sys.argv) != 2: sys.exit(__doc__)
    cut(Path(sys.argv[1]).expanduser(), Path(__file__).resolve().parent.parent/'assets')
