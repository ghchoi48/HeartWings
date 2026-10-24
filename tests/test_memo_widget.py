"""메모의 서식·인스턴스 분리·저장 실패 복구 검증."""

import unittest
from unittest.mock import patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.database import Database, DatabaseError
from maeumnarae.repositories.home_repo import HomeRepository
from maeumnarae.core.settings_store import SettingsStore
from maeumnarae.widgets.memo import Memo


def test_note_persistence_isolation_and_safe_html(tmp_path):
    db = Database('memo-test', tmp_path / 'app.db')
    db.initialize()
    repo = HomeRepository(db)
    repo.save_note('memo-a', '<p><strong>첫 메모</strong></p><ul><li>항목</li></ul><script>alert(1)</script>')
    repo.save_note('memo-b', '<p>두 번째</p>')
    saved = HomeRepository(db)
    assert '<strong>첫 메모</strong>' in saved.note('memo-a')
    assert '<li>항목</li>' in saved.note('memo-a')
    assert 'script' not in saved.note('memo-a')
    assert saved.note('memo-b') == '<p>두 번째</p>'
    repo.save_layout([])
    assert saved.note('memo-a')
    repo.save_note('memo-a', '')
    assert saved.note('memo-a') == ''
    with pytest.raises(ValueError):
        repo.save_note('memo-a', 'a' * 100001)


class MemoWidgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_save_keeps_draft_across_rebuild_and_retry(self):
        store = SettingsStore(None)
        store.update(lambda data: data.update(widgets={'layout': [], 'todos': [], 'next_todo_id': 1}))
        repo = HomeRepository(None, store)
        with Client(page('/memo-test')):
            host = ui.column()
            with host, patch('maeumnarae.widgets.memo.ui.timer'):
                memo = Memo(repo, None, 'memo-a')
                memo.build()
                memo.load()
                with patch.object(repo, 'save_note', side_effect=DatabaseError('저장 실패')):
                    memo.editor.value = '<b>초안</b>'
                    memo.save(memo.editor.value)
                assert repo.note_drafts['memo-a'] == '<b>초안</b>'
                other = Memo(repo, None, 'memo-a')
                other.build()
                other.load()
                assert other.editor.value == '<b>초안</b>'
                other.retry_action()
                assert repo.note('memo-a') == '<b>초안</b>'
                assert 'memo-a' not in repo.note_drafts
            host.delete()
