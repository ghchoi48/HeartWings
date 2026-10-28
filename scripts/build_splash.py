"""기존 로고와 번들 한글 글꼴로 Windows 시작 화면을 재생성한다."""

from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maeumnarae.core.program_info import AUTHOR


def main() -> None:
    scale = 2
    canvas = Image.new('RGB', (480 * scale, 320 * scale), '#fbf8f0')
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, canvas.width - 1, canvas.height - 1), outline='#e7dfcd', width=2)
    with Image.open(ROOT / 'resources/icons/logo.png') as source:
        logo = source.convert('RGBA')
        logo.thumbnail((128 * scale, 128 * scale), Image.Resampling.LANCZOS)
        canvas.paste(logo, ((canvas.width - logo.width) // 2, 32 * scale), logo)
    font_path = ROOT / 'resources/fonts/NotoSansKR-VariableFont_wght.ttf'
    title = ImageFont.truetype(str(font_path), 30 * scale)
    title.set_variation_by_axes([700])
    body = ImageFont.truetype(str(font_path), 14 * scale)
    body.set_variation_by_axes([400])
    credit = ImageFont.truetype(str(font_path), 11 * scale)
    credit.set_variation_by_axes([400])
    draw.text((240 * scale, 190 * scale), '마음나래', font=title, fill='#51442b', anchor='mm')
    draw.text((240 * scale, 238 * scale), 'Wee클래스·센터 상담기록 관리 시스템',
              font=body, fill='#776c58', anchor='mm')
    draw.text((240 * scale, 278 * scale), '앱을 시작하고 있습니다…',
              font=body, fill='#24756b', anchor='mm')
    draw.text((240 * scale, 303 * scale), f'made by {AUTHOR}',
              font=credit, fill='#776c58', anchor='mm')
    canvas.resize((480, 320), Image.Resampling.LANCZOS).save(ROOT / 'resources/icons/splash.png')


if __name__ == '__main__':
    main()
