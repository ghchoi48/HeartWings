"""Export committed square PNG masters to Windows and macOS icon containers."""
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1] / 'resources' / 'icons'


def main():
    for name in ('icon', 'icon-dark'):
        with Image.open(ROOT / f'{name}.png') as source:
            if source.width != source.height or source.width < 1024:
                raise ValueError(f'{name}: expected a square master of at least 1024px')
            master = source.convert('RGBA').resize((1024, 1024), Image.Resampling.LANCZOS)
            master.save(ROOT / f'{name}.ico', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
            master.save(ROOT / f'{name}.icns', sizes=[(n, n) for n in (16, 32, 64, 128, 256, 512, 1024)])


if __name__ == '__main__':
    main()
