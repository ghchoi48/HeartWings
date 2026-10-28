"""Export committed square PNG masters to Windows and macOS icon containers."""
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1] / 'resources' / 'icons'


def desktop_icon(source: Image.Image) -> Image.Image:
    """Apply the desktop silhouette explicitly; legacy icon APIs do not mask it."""
    # Render at 2x for smooth corners, keeping the same silhouette on both OSes.
    size, inset, radius = 2048, 200, 360
    tile_size = size - 2 * inset
    tile = source.convert('RGBA').resize((tile_size, tile_size), Image.Resampling.LANCZOS)
    mask = Image.new('L', tile.size)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, tile_size - 1, tile_size - 1), radius=radius, fill=255)
    tile.putalpha(mask)
    canvas = Image.new('RGBA', (size, size))
    canvas.alpha_composite(tile, (inset, inset))
    return canvas.resize((1024, 1024), Image.Resampling.LANCZOS)


def main():
    for name in ('icon', 'icon-dark'):
        with Image.open(ROOT / f'{name}.png') as source:
            if source.width != source.height or source.width < 1024:
                raise ValueError(f'{name}: expected a square master of at least 1024px')
            master = desktop_icon(source)
            master.save(ROOT / f'{name}-desktop.png')
            master.save(ROOT / f'{name}.ico', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
            master.save(ROOT / f'{name}.icns', sizes=[(n, n) for n in (16, 32, 64, 128, 256, 512, 1024)])


if __name__ == '__main__':
    main()
