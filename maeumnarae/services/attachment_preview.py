"""첨부파일을 디스크에 풀지 않고 제한된 크기의 PNG로 렌더링한다."""
import base64
from contextlib import closing
from dataclasses import dataclass
from io import BytesIO
import math
from pathlib import Path
from threading import Event, Lock
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
import pypdfium2 as pdfium

from maeumnarae.repositories.journals.attachment_repo import MAX_ATTACHMENT_BYTES

IMAGE_FORMATS = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP',
                 '.gif': 'GIF', '.bmp': 'BMP'}
MAX_INPUT_PIXELS = 40_000_000
MAX_OUTPUT_PIXELS = 8_000_000
MAX_OUTPUT_SIDE = 4096
MAX_DOCUMENT_PIXELS = 32_000_000
_pdf_lock = Lock()


class PreviewError(ValueError):
    pass


@dataclass(frozen=True)
class TextGlyph:
    text: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class PreviewPage:
    source: str
    pages: int
    width: float
    height: float
    text: tuple[TextGlyph, ...] = ()


def can_preview(filename: str) -> bool:
    return Path(filename).suffix.lower() in {*IMAGE_FORMATS, '.pdf'}


def _scale(width, height, desired=1.0, pixel_limit=MAX_OUTPUT_PIXELS):
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise PreviewError('파일의 화면 크기가 올바르지 않습니다.')
    # PDFium rounds bitmap dimensions up; leave a pixel of room on each axis.
    return min(desired, (MAX_OUTPUT_SIDE - 1) / width, (MAX_OUTPUT_SIDE - 1) / height,
               (math.sqrt(pixel_limit) - 2) / math.sqrt(width * height))


def _result(image, pages, width, height, text=()):
    with BytesIO() as output:
        image.save(output, format='PNG')
        source = 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')
    return PreviewPage(source, pages, width, height, text)


def _text_layer(page, bitmap, cancelled):
    """렌더링 좌표 변환을 공유하여 회전·크롭된 PDF도 같은 위치에 선택 영역을 둔다."""
    glyphs = []
    convert = bitmap.get_posconv(page)
    with closing(page.get_textpage()) as textpage:
        for index in range(textpage.count_chars()):
            if cancelled is not None and cancelled.is_set():
                return ()
            codepoint = pdfium.raw.FPDFText_GetUnicode(textpage, index)
            if not codepoint or codepoint > 0x10ffff:
                continue
            char = chr(codepoint)
            left, bottom, right, top = textpage.get_charbox(index)
            points = [convert.to_bitmap(x, y) for x in (left, right) for y in (bottom, top)]
            x, y = min(p[0] for p in points), min(p[1] for p in points)
            width = max(p[0] for p in points) - x
            height = max(p[1] for p in points) - y
            if width <= 0 or height <= 0:
                # PDFium-generated whitespace has no visible glyph box.
                if char.isspace() and glyphs:
                    previous = glyphs[-1]
                    glyphs.append(TextGlyph(char, previous.x + previous.width, previous.y, 0, previous.height))
                continue
            glyphs.append(TextGlyph(char, x / bitmap.width, y / bitmap.height,
                                    width / bitmap.width, height / bitmap.height))
    return tuple(glyphs)


def render_document(filename: str, content: bytes, zoom: int = 100,
                    cancelled: Event | None = None) -> list[PreviewPage]:
    """PDF 전체를 순서대로 렌더링하되 전체 해상도 예산과 닫기 요청을 지킨다."""
    if Path(filename).suffix.lower() != '.pdf':
        return [render_preview(filename, content, zoom=zoom)]
    if not content or len(content) > MAX_ATTACHMENT_BYTES or not content.startswith(b'%PDF-'):
        raise PreviewError('비어 있거나 올바르지 않은 PDF 파일입니다.')
    if type(zoom) is not int or not 25 <= zoom <= 300:
        raise PreviewError('확대 비율이 올바르지 않습니다.')
    try:
        with _pdf_lock, pdfium.PdfDocument(content) as document:
            count = len(document)
            if not count:
                raise PreviewError('표시할 PDF 페이지가 없습니다.')
            limit = min(MAX_OUTPUT_PIXELS, MAX_DOCUMENT_PIXELS / count)
            results = []
            for index in range(count):
                if cancelled is not None and cancelled.is_set():
                    return []
                with closing(document[index]) as page:
                    width, height = page.get_size()
                    scale = _scale(width, height, 1.5 * zoom / 100, limit)
                    with closing(page.render(scale=scale)) as bitmap:
                        text = _text_layer(page, bitmap, cancelled)
                        with bitmap.to_pil() as image:
                            results.append(_result(image, count, width * 1.5, height * 1.5, text))
            return results
    except pdfium.PdfiumError as error:
        raise PreviewError('PDF를 열 수 없습니다. 손상되었거나 비밀번호가 필요한 파일입니다.') from error


def render_preview(filename: str, content: bytes, page: int = 1, zoom: int = 100) -> PreviewPage:
    """각 호출이 모든 디코더 자원을 닫는다. PDFium은 프로세스 내 직렬 실행한다."""
    if not content or len(content) > MAX_ATTACHMENT_BYTES:
        raise PreviewError('비어 있거나 20MB를 초과하는 파일은 미리볼 수 없습니다.')
    if type(page) is not int or page < 1 or type(zoom) is not int or not 25 <= zoom <= 300:
        raise PreviewError('페이지 또는 확대 비율이 올바르지 않습니다.')
    suffix = Path(filename).suffix.lower()
    if suffix == '.pdf':
        if not content.startswith(b'%PDF-'):
            raise PreviewError('파일 내용이 PDF 형식과 일치하지 않습니다.')
        try:
            with _pdf_lock, pdfium.PdfDocument(content) as document:
                pages = len(document)
                if not 1 <= page <= pages:
                    raise PreviewError('표시할 PDF 페이지가 없습니다.')
                with closing(document[page - 1]) as pdf_page:
                    width, height = pdf_page.get_size()
                    scale = _scale(width, height, 1.5 * zoom / 100)
                    with closing(pdf_page.render(scale=scale)) as bitmap:
                        with bitmap.to_pil() as image:
                            return _result(image, pages, width * 1.5, height * 1.5)
        except pdfium.PdfiumError as error:
            raise PreviewError('PDF를 열 수 없습니다. 손상되었거나 비밀번호가 필요한 파일입니다.') from error
    if suffix not in IMAGE_FORMATS:
        raise PreviewError('미리보기를 지원하지 않는 파일 형식입니다.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as original:
                if original.format != IMAGE_FORMATS[suffix]:
                    raise PreviewError('파일 내용이 이미지 확장자와 일치하지 않습니다.')
                if original.width * original.height > MAX_INPUT_PIXELS:
                    raise PreviewError('이미지 해상도가 너무 큽니다. 다운로드하여 확인해 주세요.')
                original.seek(0)
                with ImageOps.exif_transpose(original) as oriented:
                    width, height = oriented.size
                    scale = _scale(width, height)
                    oriented.thumbnail((max(1, int(width * scale)), max(1, int(height * scale))))
                    with oriented.convert('RGBA') as image:
                        return _result(image, 1, width, height)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise PreviewError('이미지 해상도가 너무 큽니다. 다운로드하여 확인해 주세요.') from error
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        raise PreviewError('이미지를 열 수 없습니다. 파일이 손상되었는지 확인해 주세요.') from error
