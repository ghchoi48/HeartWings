"""Distribution check runs without UI or a user DB, including failure reporting."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DistributionCheck(unittest.TestCase):
    def test_source_execution_and_corrupt_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / 'report.json'
            fixture = ROOT / 'tests/fixtures/legacy_import/synthetic.xlsb'
            command = [sys.executable, str(ROOT / 'main.py'), '--verify-distribution', str(fixture),
                       '--verification-report', str(report)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(report.read_text())
            baseline = json.loads(fixture.with_name('baseline.json').read_text())
            self.assertEqual(data['fingerprint'], baseline['fingerprint'])
            self.assertEqual(data['status'], 'passed')
            self.assertFalse(data['frozen'])
            self.assertEqual(data['row_numbers'], {'인적사항등록': [7], '상담대장': [6]})
            corrupt = Path(tmp) / 'bad.xlsb'
            corrupt.write_bytes(b'not a workbook')
            command[3] = str(corrupt)
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(report.read_text())['status'], 'failed')
            self.assertFalse(list(Path(tmp).glob('*.db')))


if __name__ == '__main__':
    unittest.main()
