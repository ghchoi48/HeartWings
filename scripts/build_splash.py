"""기존 로고와 번들 한글 글꼴로 Windows 시작 화면을 재생성한다."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    scale = 2
    canvas = Image.new('RGB', (480 * scale, 320 * scale), '#fbf8f0')
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, canvas.width - 1, canvas.height - 1), outline='#e7dfcd', width=2)
    with Image.open(ROOT / 'resources/icons/logo.png') as source:
        logo = source.convert('RGBA')
        logo.thumbnail((128 * scale, 128 * scale), Image.Resampling.LANCZOS)
        canvas.paste(logo, ((canvas.width - logo.width) // 2, 32 * scale), logo)
    fonts = ROOT / 'resources/fonts/SpoqaHanSansNeo'
    title = ImageFont.truetype(str(fonts / 'SpoqaHanSansNeo-Bold.otf'), 30 * scale)
    body = ImageFont.truetype(str(fonts / 'SpoqaHanSansNeo-Regular.otf'), 14 * scale)
    draw.text((240 * scale, 190 * scale), '마음나래', font=title, fill='#51442b', anchor='mm')
    draw.text((240 * scale, 238 * scale), '학생들의 이야기를 안전하게',
              font=body, fill='#776c58', anchor='mm')
    draw.text((240 * scale, 278 * scale), '앱을 시작하고 있습니다…',
              font=body, fill='#24756b', anchor='mm')
    canvas.resize((480, 320), Image.Resampling.LANCZOS).save(ROOT / 'resources/icons/splash.png')


if __name__ == '__main__':
    main()
