"""공식 리디바탕 OTF를 ReportLab용 TTF로 변환한다 (개발 도구 fontTools 필요)."""
from pathlib import Path
import sys

from fontTools.ttLib import TTFont, newTable
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen


def convert(source: Path, destination: Path) -> None:
    font = TTFont(source)
    glyph_set = font.getGlyphSet()
    glyphs = {}
    for name in font.getGlyphOrder():
        pen = TTGlyphPen(None)
        glyph_set[name].draw(Cu2QuPen(pen, max_err=1.0, reverse_direction=True))
        glyphs[name] = pen.glyph()
    del font['CFF ']
    for tag in ('VORG', 'DSIG'):
        if tag in font:
            del font[tag]
    font['glyf'] = newTable('glyf')
    font['glyf'].glyphs = glyphs
    font['glyf'].glyphOrder = font.getGlyphOrder()
    font['loca'] = newTable('loca')
    font['maxp'] = newTable('maxp')
    font['maxp'].tableVersion = 0x00010000
    for field in ('maxZones', 'maxTwilightPoints', 'maxStorage', 'maxFunctionDefs',
                  'maxInstructionDefs', 'maxStackElements', 'maxSizeOfInstructions'):
        setattr(font['maxp'], field, 2 if field == 'maxZones' else 0)
    font['post'].formatType = 2.0
    font['post'].extraNames = []
    font['post'].mapping = {}
    font.sfntVersion = '\x00\x01\x00\x00'
    names = {1: 'HeartWings Ridi Batang', 2: 'Regular', 3: 'HeartWingsRidiBatang-Regular-1.0',
             4: 'HeartWings Ridi Batang Regular', 6: 'HeartWingsRidiBatang-Regular',
             16: 'HeartWings Ridi Batang', 17: 'Regular'}
    for record in font['name'].names:
        if record.nameID in names:
            record.string = names[record.nameID].encode(record.getEncoding())
    destination.parent.mkdir(parents=True, exist_ok=True)
    font.save(destination)


if __name__ == '__main__':
    convert(Path(sys.argv[1]), Path(sys.argv[2]))
