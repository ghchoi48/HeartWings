"""pyxlsb의 평문 임시파일 대신 ZIP 스트림으로 XLSB를 읽는다."""

from contextlib import ExitStack, contextmanager
from io import BytesIO
from posixpath import normpath
from zipfile import ZipFile

from defusedxml.ElementTree import parse
from pyxlsb import biff12
from pyxlsb.reader import BIFF12Reader
from pyxlsb.stringtable import StringTable
from pyxlsb.workbook import Workbook
from pyxlsb.worksheet import Worksheet


class MemoryWorkbook(Workbook):
    def __init__(self, archive, streams):
        self.streams = streams
        super().__init__(archive)

    def _parse(self):
        with self._zf.open('xl/_rels/workbook.bin.rels') as stream:
            relationships = {element.attrib['Id']: element.attrib['Target']
                             for element in parse(stream).getroot()}
        with self._zf.open('xl/workbook.bin') as stream:
            for kind, record in BIFF12Reader(stream):
                if kind == biff12.SHEET:
                    self._sheets.append((record.name, relationships[record.rId]))
                elif kind == biff12.SHEETS_END:
                    break
        if 'xl/sharedStrings.bin' in self._zf.namelist():
            self.stringtable = StringTable(self.streams.enter_context(self._zf.open('xl/sharedStrings.bin')))

    def get_sheet(self, idx, rels=False):
        if rels:
            raise ValueError('XLSB 외부 관계 조회는 지원하지 않습니다.')
        if isinstance(idx, str):
            idx = [name.lower() for name, _ in self._sheets].index(idx.lower()) + 1
        if not 1 <= idx <= len(self._sheets):
            raise IndexError('sheet index out of range')
        name, target = self._sheets[idx - 1]
        path = normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
        if not path.startswith('xl/'):
            raise ValueError('XLSB 시트 경로가 올바르지 않습니다.')
        stream = self.streams.enter_context(self._zf.open(path))
        return Worksheet(name, stream, stringtable=self.stringtable)


@contextmanager
def open_memory_workbook(content):
    with ExitStack() as streams:
        archive = streams.enter_context(ZipFile(BytesIO(content)))
        workbook = MemoryWorkbook(archive, streams)
        try:
            yield workbook
        finally:
            workbook.close()
