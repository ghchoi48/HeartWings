"""Reader boundary, resource lifetime and moved limits."""
from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from maeumnarae.services import legacy_import, memory_xlsb, xlsb_reader

FIXTURES = Path(__file__).parent / 'fixtures' / 'legacy_import'


class ReaderContract(unittest.TestCase):
    def setUp(self):
        self.content = (FIXTURES / 'synthetic.xlsb').read_bytes()
        self.baseline = json.loads((FIXTURES / 'baseline.json').read_text())

    def test_public_rows_match_original_without_library_objects(self):
        with xlsb_reader.open_workbook(self.content) as book:
            for name, original in self.baseline['raw_cells'].items():
                with book.read_sheet(name) as rows:
                    actual = list(rows)
                self.assertEqual(actual, [xlsb_reader.SheetRow(cells[0][0] + 1,
                                 tuple(c[2] for c in cells)) for cells in original])

    def test_business_rules_accept_replacement_reader(self):
        baseline = self.baseline
        closed = []

        class FakeReader:
            @contextmanager
            def read_sheet(self, name):
                try:
                    yield iter(xlsb_reader.SheetRow(cells[0][0] + 1, tuple(c[2] for c in cells))
                               for cells in baseline['raw_cells'][name])
                finally:
                    closed.append(name)

        @contextmanager
        def fake_open(content):
            yield FakeReader()

        with patch.object(xlsb_reader, 'open_workbook', fake_open):
            actual = legacy_import.read_rows(b'not a ZIP; handled by replacement')
        self.assertEqual(json.loads(json.dumps(actual)), baseline['rows'])
        self.assertEqual(closed, ['인적사항등록', '상담대장'])
        from datetime import date
        with patch.object(xlsb_reader, 'serial_date', return_value=date(2026, 1, 2)) as convert:
            self.assertEqual(legacy_import.excel_day(123), date(2026, 1, 2))
            convert.assert_called_once_with(123)

    def test_business_module_import_does_not_load_pyxlsb(self):
        result = subprocess.run([sys.executable, '-c', '''
import sys
class BlockPyxlsb:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'pyxlsb' or fullname.startswith('pyxlsb.'):
            raise AssertionError('business module imports backend eagerly')
sys.meta_path.insert(0, BlockPyxlsb())
from maeumnarae.services import legacy_import
assert 'pyxlsb' not in sys.modules
'''], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_input_archive_and_sheet_limits(self):
        for content in (b'', b'x' * (xlsb_reader.MAX_BYTES + 1)):
            with self.assertRaisesRegex(ValueError, '10MB'):
                with xlsb_reader.open_workbook(content):
                    pass
        with self.assertRaisesRegex(ValueError, 'XLSB 파일을 읽지 못했습니다'):
            with xlsb_reader.open_workbook(b'bad zip'):
                pass
        output = BytesIO()
        with ZipFile(output, 'w') as archive:
            for i in range(513):
                archive.writestr(str(i), b'')
        with self.assertRaisesRegex(ValueError, '압축 해제 크기'):
            with xlsb_reader.open_workbook(output.getvalue()):
                pass
        # Exercise the size branch with a small fixture rather than allocate 80 MB.
        with patch.object(memory_xlsb, 'MAX_UNCOMPRESSED_BYTES', 1):
            with self.assertRaisesRegex(ValueError, '압축 해제 크기'):
                with xlsb_reader.open_workbook(self.content):
                    pass
        for limit, message in [('MAX_ROWS', '20,000행'), ('MAX_COLUMNS', '100열')]:
            with patch.object(memory_xlsb, limit, 1):
                with self.assertRaisesRegex(ValueError, message):
                    with xlsb_reader.open_workbook(self.content) as book:
                        with book.read_sheet('인적사항등록'):
                            pass

    def test_streams_close_on_early_exit_and_consumer_error(self):
        original = memory_xlsb.ZipFile
        for fail in (False, True):
            archives, streams = [], []

            def tracked_zip(*args, **kwargs):
                archive = original(*args, **kwargs)
                archives.append(archive)
                original_open = archive.open

                def tracked_open(*a, **k):
                    stream = original_open(*a, **k)
                    streams.append(stream)
                    return stream

                archive.open = tracked_open
                return archive

            with patch.object(memory_xlsb, 'ZipFile', tracked_zip):
                try:
                    with xlsb_reader.open_workbook(self.content) as book:
                        with book.read_sheet('인적사항등록') as rows:
                            next(rows)
                            if fail:
                                raise ValueError('consumer failure')
                except ValueError as error:
                    self.assertTrue(fail)
                    self.assertEqual(str(error), 'consumer failure')
            self.assertTrue(streams)
            self.assertTrue(all(s.closed for s in streams))
            self.assertTrue(all(a.fp is None for a in archives))


if __name__ == '__main__':
    unittest.main()
