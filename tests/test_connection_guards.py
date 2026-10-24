"""외부 패키지 없이 평문 드라이버 거부와 경로 처리 계약을 검사한다."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maeumnarae.core.database import Database, DatabaseError, DatabaseOpenError, default_database_path


class ConnectionGuardTests(unittest.TestCase):
    def test_plain_sqlite_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('maeumnarae.core.database.import_module', return_value=sqlite3):
                database = Database('test-only', Path(directory) / 'test.db')
            with self.assertRaises(DatabaseOpenError):
                database.initialize()

    def test_missing_driver_has_no_fallback(self):
        with patch('maeumnarae.core.database.import_module', side_effect=ImportError):
            with self.assertRaises(DatabaseError):
                Database('test-only')

    def test_password_rejects_empty_and_nul(self):
        for password in ('', 'bad\x00password'):
            with self.assertRaises(ValueError):
                Database(password)

    def test_default_path_is_absolute(self):
        self.assertTrue(default_database_path().is_absolute())


if __name__ == '__main__':
    unittest.main()
