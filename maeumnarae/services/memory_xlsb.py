# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) William Turner (upstream pyxlsb author)
# Copyright (c) 2026 Gyuho Choi (HeartWings modifications)
# Derived from pyxlsb 1.0.10, pyxlsb/workbook.py (Workbook._parse/get_sheet).
# Attribution and modification notice added 2026-10-29; original edit date unknown.
# Changes: ZIP streams and ExitStack instead of TemporaryFile; defusedxml;
# normalized archive paths; external relationship loading rejected.
# 2026-10-29: added app reader adapter, limits and serial date conversion boundary.
# 2026-10-29: validate dimension end positions before allocating row values.
# This file is provided under LGPL-3.0-or-later, not the project MIT license.
# See resources/licenses/pyxlsb/{COPYING,COPYING.LESSER,PROVENANCE.md}.
"""pyxlsb의 평문 임시파일 대신 ZIP 스트림으로 XLSB를 읽는 LGPL 파생 구현."""

from contextlib import ExitStack, contextmanager
from io import BytesIO
from posixpath import normpath
from zipfile import ZipFile

from defusedxml.ElementTree import parse
from pyxlsb import biff12, convert_date
from pyxlsb.reader import BIFF12Reader
from pyxlsb.stringtable import StringTable
from pyxlsb.workbook import Workbook
from pyxlsb.worksheet import Worksheet

from maeumnarae.services.xlsb_reader import (
    MAX_BYTES, MAX_ARCHIVE_ENTRIES, MAX_UNCOMPRESSED_BYTES, MAX_ROWS, MAX_COLUMNS,
    SheetRow,
)


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


class _Reader:
    def __init__(self, workbook):
        self._workbook = workbook

    @contextmanager
    def read_sheet(self, name):
        with self._workbook.get_sheet(name) as sheet:
            if (sheet.dimension.r + sheet.dimension.h > MAX_ROWS
                    or sheet.dimension.c + sheet.dimension.w > MAX_COLUMNS):
                raise ValueError('시트는 최대 20,000행, 100열까지 지원합니다.')
            rows = self._rows(sheet)
            try:
                yield rows
            finally:
                rows.close()

    @staticmethod
    def _rows(sheet):
        for cells in sheet.rows(sparse=True):
            number = cells[0].r + 1
            if number > MAX_ROWS or len(cells) > MAX_COLUMNS:
                raise ValueError('시트 크기 제한을 초과했습니다.')
            yield SheetRow(number, tuple(cell.v for cell in cells))


@contextmanager
def open_reader(content):
    if not content or len(content) > MAX_BYTES:
        raise ValueError('10MB 이하의 XLSB 파일을 선택하세요.')
    with ZipFile(BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_ENTRIES or sum(i.file_size for i in entries) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError('압축 해제 크기가 너무 큽니다.')
    with open_memory_workbook(content) as workbook:
        yield _Reader(workbook)


def serial_date(value):
    return convert_date(value).date()
