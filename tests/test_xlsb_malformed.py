"""Exercise real BIFF/ZIP limit records and cleanup on malformed inputs."""
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
from struct import pack
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from maeumnarae.services import legacy_import, memory_xlsb

FIXTURE = Path(__file__).parent / 'fixtures/legacy_import/synthetic.xlsb'


def altered(name, change):
    output = BytesIO()
    with ZipFile(FIXTURE) as source, ZipFile(output, 'w', compression=ZIP_DEFLATED) as target:
        for member in source.namelist():
            data = source.read(member)
            target.writestr(member, change(data) if member == name else data)
    return output.getvalue()


class MalformedXlsb(unittest.TestCase):
    def test_actual_dimensions_and_row_limit(self):
        for original, replacement in [
            (pack('<IIII', 0, 9, 0, 10), pack('<IIII', 0, 20000, 0, 10)),
            (pack('<IIII', 0, 9, 0, 10), pack('<IIII', 0, 9, 0, 100)),
            # A small width with a distant starting column must not allocate huge rows.
            (pack('<IIII', 0, 9, 0, 10), pack('<IIII', 0, 9, 1000000, 1000010)),
        ]:
            with self.subTest(replacement=replacement):
                data = altered('xl/worksheets/sheet1.bin', lambda b: b.replace(original, replacement, 1))
                with self.assertRaisesRegex(ValueError, '20,000행, 100열'):
                    legacy_import.read_rows(data)
        # A lying dimension cannot authorize row 20001.
        data = altered('xl/worksheets/sheet1.bin',
                       lambda b: b.replace(b'\x00\x04' + pack('<I', 6), b'\x00\x04' + pack('<I', 20000), 1))
        with self.assertRaisesRegex(ValueError, '시트 크기 제한'):
            legacy_import.read_rows(data)

    def test_xml_entities_and_archive_traversal(self):
        data = altered('xl/_rels/workbook.bin.rels', lambda b:
                       b'<!DOCTYPE a [<!ENTITY x "bad">]>' + b.replace(b'worksheets/sheet1.bin', b'&x;'))
        with self.assertRaises(ValueError):
            legacy_import.read_rows(data)
        data = altered('xl/_rels/workbook.bin.rels', lambda b:
                       b.replace(b'worksheets/sheet1.bin', b'../../outside.bin'))
        with self.assertRaisesRegex(ValueError, '시트 경로'):
            legacy_import.read_rows(data)

    def test_no_plaintext_temp_files_on_success_or_error(self):
        good = FIXTURE.read_bytes()
        bad = altered('xl/workbook.bin', lambda b: b'broken')
        with ExitStack() as stack:
            for target in ['tempfile.TemporaryFile', 'tempfile.NamedTemporaryFile', 'tempfile.mkstemp',
                           'pyxlsb.workbook.TemporaryFile']:
                stack.enter_context(patch(target, side_effect=AssertionError('plaintext temporary file')))
            legacy_import.read_rows(good)
            with self.assertRaises(ValueError):
                legacy_import.read_rows(bad)

    def test_streams_close_when_parser_fails_during_construction(self):
        data = altered('xl/workbook.bin', lambda b: b'broken')
        archives = []
        original = memory_xlsb.ZipFile

        def tracked(*args, **kwargs):
            archive = original(*args, **kwargs)
            archives.append(archive)
            return archive

        with patch.object(memory_xlsb, 'ZipFile', tracked):
            with self.assertRaises(ValueError):
                legacy_import.read_rows(data)
        self.assertTrue(archives)
        self.assertTrue(all(a.fp is None for a in archives))


if __name__ == '__main__':
    unittest.main()
