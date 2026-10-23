"""첨부파일 격리·암호화·연쇄 삭제 및 실제 UI 업로드 흐름 검증."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from database import ConflictError, Database, NotFoundError, SCHEMA_VERSION
from models import (StudentInput, TeacherInput, CounselingInput, SpecialEducationInput,
                    GroupCounselingInput, GroupLogInput, ConsultationInput,
                    PsychologicalTestInput, EducationEventInput)
from repositories.student_repo import StudentRepository
from repositories.teacher_repo import TeacherRepository
from repositories.counseling_repo import CounselingRepository
from repositories.special_education_repo import SpecialEducationRepository, SpecialEducationLogRepository
from repositories.group_counseling_repo import GroupCounselingRepository
from repositories.consultation_repo import ConsultationRepository
from repositories.psychological_test_repo import PsychologicalTestRepository
from repositories.education_event_repo import EducationEventRepository
from repositories.attachment_repo import AttachmentRepository, Attachment, MAX_ATTACHMENT_BYTES
from repositories.deletion_repo import DeletionRepository
from services.database_maintenance import create_backup
from views.attachment_view import AttachmentView


@pytest.fixture
def records(tmp_path):
    db = Database('attachment-test', tmp_path / 'records.db')
    db.initialize()
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    teacher = TeacherRepository(db).save(TeacherInput(name='교사'))
    start = datetime.now(timezone.utc)
    individual = CounselingRepository(db).create(CounselingInput(student_id=student.id, title='일지', starts_at=start))
    special = SpecialEducationRepository(db).save(SpecialEducationInput(student_id=student.id, title='교육', law='교원지위법'))
    special_log = SpecialEducationLogRepository(db).create(CounselingInput(student_id=student.id, case_id=special.id, title='일지', starts_at=start))
    groups = GroupCounselingRepository(db)
    group = groups.save(GroupCounselingInput(name='집단', student_ids=[student.id]))
    group_log = groups.save_log(GroupLogInput(group_id=group.id, title='일지', starts_at=start))
    consultation = ConsultationRepository(db).save(ConsultationInput(teacher_id=teacher.id, title='일지', starts_at=start))
    test = PsychologicalTestRepository(db).save(PsychologicalTestInput(student_id=student.id, title='검사', test_date=start.date()))
    education = EducationEventRepository(db).save(EducationEventInput(title='행사', event_date=start.date()))
    return db, dict(counseling=individual.id, special_log=special_log.id, group_log=group_log.id,
                    consultation=consultation.id, test=test.id, education=education.id), dict(
                        student=student.id, teacher=teacher.id, case=individual.case_id, special=special.id, group=group.id)


def test_all_journals_isolation_and_backup(records, tmp_path):
    db, ids, _ = records
    content = b'private-attachment-content-1234567890\x00\xff'
    for kind, record_id in ids.items():
        repo = AttachmentRepository(db, kind, record_id)
        repo.add('첨부.txt', content + kind.encode())
        repo.add('첨부.txt', b'')  # 같은 이름과 빈 파일도 개별 파일로 유지한다.
        entries = repo.list()
        assert len(entries) == 2 and entries[0].id != entries[1].id
        assert entries[0].size == len(content + kind.encode())
        assert repo.download(entries[0].id) == ('첨부.txt', content + kind.encode())
        wrong = AttachmentRepository(db, kind, record_id + 100)
        with pytest.raises(NotFoundError):
            wrong.download(entries[0].id)
        with pytest.raises(NotFoundError):
            wrong.delete(entries[0].id)
        repo.delete(entries[1].id)
    individual = AttachmentRepository(db, 'counseling', ids['counseling'])
    group = AttachmentRepository(db, 'group_log', ids['group_log'])
    with pytest.raises(NotFoundError):
        group.download(individual.list()[0].id)
    backup_path = tmp_path / 'backup.db'
    backup_path.write_bytes(create_backup(db))
    assert content not in backup_path.read_bytes()
    restored = Database('attachment-test', backup_path)
    restored.initialize()
    for kind, record_id in ids.items():
        repo = AttachmentRepository(restored, kind, record_id)
        assert repo.download(repo.list()[0].id)[1] == content + kind.encode()


@pytest.mark.parametrize('parent, removed', [
    ('student', {'counseling', 'special_log', 'test'}), ('case', {'counseling'}),
    ('special', {'special_log'}), ('teacher', {'consultation'}), ('group', {'group_log'}),
])
def test_parent_delete_cascades_only_owned_attachments(records, parent, removed):
    db, ids, parents = records
    for kind, record_id in ids.items():
        AttachmentRepository(db, kind, record_id).add(kind, b'data')
    DeletionRepository(db).delete(parent, parents[parent])
    with db.session() as connection:
        names = {row[0] for row in connection.execute('SELECT filename FROM journal_attachments')}
        assert names == set(ids) - removed
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()


def test_log_delete_cascades_and_missing_owner_cannot_upload(records):
    db, ids, _ = records
    for kind, record_id in ids.items():
        repo = AttachmentRepository(db, kind, record_id)
        repo.add('파일.pdf', b'pdf')
        entry = repo.list()[0]
        DeletionRepository(db).delete(kind, record_id)
        with pytest.raises(NotFoundError):
            repo.download(entry.id)
        with pytest.raises(NotFoundError):
            repo.add('새 파일', b'no')
    with db.session() as connection:
        assert not connection.execute('SELECT * FROM journal_attachments').fetchall()


def test_migration_validation_and_rollback(records):
    db, ids, _ = records
    with db.session(write=True) as connection:
        connection.execute('DROP TABLE journal_attachments')
        connection.execute('PRAGMA user_version=37')
    db.initialize()
    db.initialize()
    repo = AttachmentRepository(db, 'counseling', ids['counseling'])
    repo.add('C:\\fakepath\\보고서\r\n.pdf', b'file')
    assert repo.list()[0].filename == '보고서.pdf'
    with pytest.raises(ValueError):
        repo.add('large', b'x' * (MAX_ATTACHMENT_BYTES + 1))
    with pytest.raises(ValueError):
        repo.add('../', b'file')
    with pytest.raises(ValueError):
        AttachmentRepository(db, 'invalid', 1)
    with db.session() as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
    with db.session(write=True) as connection:
        connection.execute("""CREATE TRIGGER prevent_counseling_delete BEFORE DELETE ON counseling
                            BEGIN SELECT RAISE(ABORT, 'test'); END""")
    with pytest.raises(ConflictError):
        DeletionRepository(db).delete('counseling', ids['counseling'])
    assert repo.download(repo.list()[0].id)[1] == b'file'


def test_upload_download_and_confirmed_delete_ui():
    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def check():
        with Client(page('/attachment-ui-test')):
            repo = Mock()
            entry = Attachment(1, '첨부.txt', 4, '2026-10-23')
            repo.list.return_value = [entry]
            repo.download.return_value = ('첨부.txt', b'data')
            view = AttachmentView(repo)
            view.build()
            file = SimpleNamespace(name='첨부.txt', size=lambda: 4, read=AsyncMock(return_value=b'data'))
            with patch('views.attachment_view.run.io_bound', side_effect=invoke), patch('views.attachment_view.ui.notify'):
                await view.receive(SimpleNamespace(file=file))
                repo.add.assert_called_once_with('첨부.txt', b'data')
                assert view.close.enabled
                with patch('views.attachment_view.ui.download.content') as download:
                    await view.download(entry)
                    download.assert_called_once_with(b'data', '첨부.txt', media_type='application/octet-stream')
                for confirmed in (False, True):
                    async def confirm(dialog):
                        return confirmed
                    with patch.object(ui.dialog, '__await__', lambda dialog: confirm(dialog).__await__()):
                        await view.remove(entry)
                    assert repo.delete.call_count == int(confirmed)
                too_large = SimpleNamespace(name='large', size=lambda: MAX_ATTACHMENT_BYTES + 1, read=AsyncMock())
                await view.receive(SimpleNamespace(file=too_large))
                too_large.read.assert_not_awaited()
                assert '20MB' in view.message.text and view.close.enabled
            view.dialog.delete()
    asyncio.run(check())


def test_concurrent_uploads_are_queued_without_losing_files():
    async def check():
        with Client(page('/attachment-concurrent-test')):
            repo = Mock()
            repo.list.return_value = []
            view = AttachmentView(repo)
            view.build()
            started, release = asyncio.Event(), asyncio.Event()

            async def invoke(function, *args):
                if function == repo.add and args[0] == 'first':
                    started.set()
                    await release.wait()
                return function(*args)

            def event(name):
                return SimpleNamespace(file=SimpleNamespace(name=name, size=lambda: 1, read=AsyncMock(return_value=b'x')))

            with patch('views.attachment_view.run.io_bound', side_effect=invoke), patch('views.attachment_view.ui.notify'):
                first = asyncio.create_task(view.receive(event('first')))
                await started.wait()
                second = asyncio.create_task(view.receive(event('second')))
                await asyncio.sleep(0)
                assert not view.close.enabled
                release.set()
                await asyncio.gather(first, second)
                assert [call.args[0] for call in repo.add.call_args_list] == ['first', 'second']
                assert view.close.enabled and view.pending == 0
            view.dialog.delete()
    asyncio.run(check())
