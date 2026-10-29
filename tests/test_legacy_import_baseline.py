"""Behavior captured before the pyxlsb adapter refactor (2026-10-29).

Run: python -m unittest discover -s tests -p 'test_legacy_import_baseline.py' -v
Requires the application's pyxlsb, defusedxml and pydantic dependencies.
"""
import hashlib
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from maeumnarae.services.legacy_import import excel_day, parse_rows, read_rows
from maeumnarae.services.memory_xlsb import open_memory_workbook

FIXTURES = Path(__file__).parent / 'fixtures' / 'legacy_import'


def normalized(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


class LegacyImportBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = (FIXTURES / 'synthetic.xlsb').read_bytes()
        cls.expected = json.loads((FIXTURES / 'baseline.json').read_text())
        cls.make_fixture = staticmethod(runpy.run_path(str(FIXTURES / 'build_fixture.py'))['make_fixture'])

    def test_fixture_integrity(self):
        self.assertEqual(hashlib.sha256(self.content).hexdigest(), self.expected['fixture_sha256'])
        self.assertEqual(self.make_fixture(), self.content)

    def test_raw_row_numbers_and_blank_columns(self):
        raw = {}
        with open_memory_workbook(self.content) as book:
            for name in book.sheets:
                with book.get_sheet(name) as sheet:
                    raw[name] = [[[c.r, c.c, c.v] for c in row] for row in sheet.rows(sparse=True)]
        self.assertEqual(raw, self.expected['raw_cells'])

    def test_headers_rows_and_ignored_formula_only_record(self):
        rows = read_rows(self.content)
        self.assertEqual(normalized(rows), self.expected['rows'])
        self.assertEqual([n for n, _ in rows['인적사항등록']], [7])
        self.assertEqual([n for n, _ in rows['상담대장']], [6])
        self.assertIsNone(rows['인적사항등록'][0][1]['소속학교'])

    def test_dates_including_excel_1900_boundary(self):
        for value, expected in self.expected['dates'].items():
            with self.subTest(value=value):
                self.assertEqual(excel_day(float(value)).isoformat(), expected)
        for value in [0, -1, True, 'invalid-date']:
            with self.subTest(invalid=value), self.assertRaises(ValueError):
                excel_day(value)

    def test_models_and_duplicate_detection_fingerprint(self):
        batch = parse_rows(read_rows(self.content), 2026, {'1': '09:00'})
        self.assertEqual(batch.fingerprint, self.expected['fingerprint'])
        self.assertEqual(list(batch.errors), self.expected['errors'])
        self.assertEqual([{'row': x.row, 'key': x.key, 'value': x.value.model_dump(mode='json')}
                          for x in batch.people], self.expected['people'])
        self.assertEqual([{'row': x.row, 'key': x.key, 'value': x.value.model_dump(mode='json'),
                           'author': x.author, 'special_law': x.special_law}
                          for x in batch.logs], self.expected['logs'])

    def test_duplicate_and_missing_headers(self):
        with self.assertRaisesRegex(ValueError, '중복된 제목 열'):
            read_rows(self.make_fixture(duplicate_header=True))
        with self.assertRaisesRegex(ValueError, '제목 행이 없습니다'):
            read_rows(self.make_fixture(missing_header=True))

    def test_reader_does_not_use_upstream_temporary_files(self):
        with patch('pyxlsb.workbook.TemporaryFile', side_effect=AssertionError('plaintext tempfile')):
            self.assertEqual(normalized(read_rows(self.content)), self.expected['rows'])


if __name__ == '__main__':
    unittest.main()
