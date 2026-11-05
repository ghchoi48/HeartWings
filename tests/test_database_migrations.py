"""Schema upgrades preserve deployed databases and backups."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from maeumnarae.core.database import Database, DatabaseError, SCHEMA_VERSION
from maeumnarae.services.database_maintenance import restore_backup


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'test.db'
        self.db = Database('test-password', self.path)
        self.db.initialize()

    def version(self, database=None):
        with (database or self.db).session() as connection:
            return connection.execute('PRAGMA user_version').fetchone()[0]

    def legacy(self):
        with self.db.session(write=True) as connection:
            connection.execute('DROP TABLE google_calendar_subscriptions')
            connection.execute('PRAGMA user_version = 1')
            connection.execute("UPDATE school_settings SET school_name='preserved'")

    def test_new_database_and_repeated_initialize(self):
        self.assertEqual(self.version(), SCHEMA_VERSION)
        self.db.initialize()
        self.assertEqual(self.version(), 2)

    def test_upgrade_preserves_existing_data(self):
        self.legacy()
        self.db.initialize()
        self.db.initialize()
        self.assertEqual(self.version(), 2)
        with self.db.session() as connection:
            self.assertEqual(connection.execute('SELECT school_name FROM school_settings').fetchone()[0], 'preserved')
            self.assertEqual(connection.execute('SELECT count(*) FROM google_calendar_subscriptions').fetchone()[0], 0)

    def test_existing_google_subscription_is_preserved(self):
        with self.db.session(write=True) as connection:
            connection.execute("INSERT INTO google_calendar_subscriptions (name, color, url, ics) VALUES ('saved', '#4285f4', 'test-url', ?)", (b'cached-feed',))
            connection.execute('PRAGMA user_version = 1')
        self.db.initialize()
        with self.db.session() as connection:
            self.assertEqual(connection.execute('SELECT ics FROM google_calendar_subscriptions').fetchone()[0], b'cached-feed')
        self.assertEqual(self.version(), 2)

    def test_failed_upgrade_rolls_back_schema_and_version(self):
        self.legacy()
        migrate = self.db._migrate_v1_to_v2

        def fail(connection):
            migrate(connection)
            raise DatabaseError('simulated failure')

        with patch.object(self.db, '_migrate_v1_to_v2', side_effect=fail):
            with self.assertRaises(DatabaseError):
                self.db.initialize()
        self.assertEqual(self.version(), 1)
        with self.db.session() as connection:
            self.assertIsNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='google_calendar_subscriptions'").fetchone())
        self.db.initialize()
        self.assertEqual(self.version(), 2)

    def test_restore_legacy_backup_upgrades_candidate(self):
        self.legacy()
        with self.db.session() as connection:
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        content = self.path.read_bytes()
        self.db.initialize()
        recovery = restore_backup(self.db, content, 'test-password')
        self.assertTrue(recovery.exists())
        restored = Database('test-password', self.path)
        self.assertEqual(self.version(restored), 2)
        with restored.session() as connection:
            self.assertEqual(connection.execute('SELECT school_name FROM school_settings').fetchone()[0], 'preserved')

    def test_unknown_version_is_rejected_without_changes(self):
        with self.db.session(write=True) as connection:
            connection.execute('PRAGMA user_version = 999')
        with self.assertRaises(DatabaseError):
            self.db.initialize()
        self.assertEqual(self.version(), 999)
