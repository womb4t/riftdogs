#!/usr/bin/env python3
"""Cut Examiner Varga's five portraits from her reference sheet (1536x1024, outside the repository).
Usage: python3 tools/cut_varga.py "RIFTDOGS Examiner Varga Reference Sheet.png"
Needs ImageMagick (magick). Writes assets/varga-<face>.bmp.gz: 224x168, 24-bit BMP, gzipped.
Each crop is the face area of an expression tile (narrow enough to leave the tile's label out), padded with the
sheet's background to 4:3 so the portrait is not stretched."""
import gzip
import subprocess
import sys
import tempfile
from pathlib import Path

SIZE = (224, 168)
BACKGROUND = '#010317'
H = 186               # height of every face area
W = 172               # width of a face area, unless narrowed below
Y = 434
# face -> (x, w) of the expression tile's face area on the sheet; 'approving' is narrower: its label sticks in further.
BOXES = {'neutral': (22, W), 'noting': (332, W), 'sceptical': (623, W), 'approving': (929, 164), 'stern': (1224, W)}


def cut(sheet, out):
    out.mkdir(parents=True, exist_ok=True)
    h = H
    padded = f'{h*4//3}x{h}'
    for face, (x, w) in BOXES.items():
        with tempfile.TemporaryDirectory() as tmp:
            bmp = Path(tmp)/f'{face}.bmp'
            subprocess.run(['magick', str(sheet), '-crop', f'{w}x{h}+{x}+{Y}', '+repage',
                            '-background', BACKGROUND, '-gravity', 'center', '-extent', padded,
                            '-filter', 'Lanczos', '-resize', f'{SIZE[0]}x{SIZE[1]}!', f'BMP3:{bmp}'], check=True)
            (out/f'varga-{face}.bmp.gz').write_bytes(gzip.compress(bmp.read_bytes(), 9, mtime=0))


if __name__ == '__main__':
    if len(sys.argv) != 2: sys.exit(__doc__)
    cut(Path(sys.argv[1]).expanduser(), Path(__file__).resolve().parent.parent/'assets')
