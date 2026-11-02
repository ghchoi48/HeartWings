"""DB 초기화는 현재 파일만 삭제하고 오래된 연결의 재접근을 차단한다."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from maeumnarae.core.database import Database, DatabaseError
from maeumnarae.services.database_maintenance import reset_database


class DatabaseResetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'test.db'
        self.database = Database('test-password', self.path)
        self.database.initialize()

    def test_reset_deletes_db_and_blocks_old_instances(self):
        other = Database('test-password', self.path)
        settings = self.path.with_name('display-settings.json')
        settings.write_text('{}')
        backup = self.path.with_name('backup.db')
        backup.write_bytes(b'keep')
        connection = self.database._connect()
        try:
            connection.execute('PRAGMA journal_mode=WAL')
        finally:
            connection.close()
        reset_database(self.database)
        self.assertFalse(self.path.exists())
        self.assertFalse(Path(str(self.path) + '-wal').exists())
        self.assertFalse(Path(str(self.path) + '-shm').exists())
        self.assertEqual(settings.read_text(), '{}')
        self.assertEqual(backup.read_bytes(), b'keep')
        for database in (self.database, other):
            with self.assertRaises(DatabaseError):
                with database.session():
                    pass
        self.assertFalse(self.path.exists())
        fresh = Database('new-password', self.path)
        fresh.initialize(onboarding=True)
        with fresh.session() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM students').fetchone()[0], 0)

    def test_delete_failure_keeps_database_usable(self):
        with patch.object(Path, 'unlink', side_effect=PermissionError):
            with self.assertRaises(DatabaseError):
                reset_database(self.database)
        self.assertTrue(self.path.exists())
        with self.database.session() as connection:
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_locked_database_cannot_be_reset(self):
        self.database.lock()
        with self.assertRaises(DatabaseError):
            reset_database(self.database)
        self.assertTrue(self.path.exists())


if __name__ == '__main__':
    unittest.main()
