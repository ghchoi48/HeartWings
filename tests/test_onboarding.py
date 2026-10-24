"""최초 설정의 유효성 검사, 자동 저장, 분기 및 재개 검증."""

import asyncio
from unittest.mock import Mock, patch

from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.database import Database, DatabaseError
from maeumnarae.repositories.onboarding_repo import OnboardingRepository
from maeumnarae.repositories.school_settings_repo import SchoolSettingsRepository
from maeumnarae.views.onboarding_view import OnboardingView
from tests.test_roster_import_view import callback


async def inline(function, *args):
    return function(*args)


def test_existing_database_does_not_start_onboarding(tmp_path):
    database = Database('key', tmp_path / 'existing.db')
    database.initialize()
    assert OnboardingRepository(database).get() is None


def test_onboarding_validation_save_resume_and_branches(tmp_path):
    async def check():
        path = tmp_path / 'new.db'
        started = Mock()
        with Client(page('/onboarding-test')), patch('maeumnarae.views.onboarding_view.run.io_bound', side_effect=inline):
            view = OnboardingView(path, started)
            view.build()
            assert view.fields['school_level'].value == '초등학교'
            await view.create_database()
            assert not path.exists()
            view.password.value = 'key'
            view.confirmation.value = 'different'
            await view.create_database()
            assert not path.exists()
            view.confirmation.value = 'key'
            await view.create_database()
            assert view.step == 'school'
            assert view.password.value == view.confirmation.value == ''
            await view.save_school()
            assert view.step == 'school'
            view.fields['neis_office_code'].value = 'H10'
            view.fields['school_name'].value = '테스트초등학교'
            view.fields['counselor_name'].value = '김교사'
            with patch.object(SchoolSettingsRepository, 'save', side_effect=DatabaseError('저장 실패')):
                await view.save_school()
            assert view.step == 'school'
            assert not view.busy
            await view.save_school()
            assert view.step == 'choice'
            assert SchoolSettingsRepository(view.database).get().counselor_name == '김교사'
            for step in ('legacy', 'choice', 'roster', 'choice', 'welcome'):
                await view.move(step)
                assert view.step == step
            assert len(view.import_views) == 3
            assert not started.called
            view.database.lock()
            reopened = Database('key', path)
            reopened.initialize()
            assert OnboardingRepository(reopened).get() == 'welcome'
            resumed = OnboardingView(path, started, reopened, 'welcome', SchoolSettingsRepository(reopened).get())
            resumed.build()
            await resumed.finish()
            started.assert_called_once_with(reopened)
            assert OnboardingRepository(reopened).get() == 'complete'
    asyncio.run(check())


def test_school_lookup_autosaves_selection_and_invalidates_changed_name(tmp_path):
    async def check():
        with Client(page('/onboarding-search-test')) as client, \
                patch('maeumnarae.views.onboarding_view.run.io_bound', side_effect=inline), \
                patch('maeumnarae.views.onboarding_view.ui.notify'):
            view = OnboardingView(tmp_path / 'new.db', Mock())
            view.build()
            view.password.value = view.confirmation.value = 'key'
            await view.create_database()
            view.fields['neis_office_code'].value = 'H10'
            view.fields['school_name'].value = '테스트'
            row = dict(SCHUL_NM='테스트초등학교', ATPT_OFCDC_SC_CODE='H10', SD_SCHUL_CODE='1234567',
                       SCHUL_KND_SC_NM='초등학교', ORG_RDNMA='울산 테스트 주소')
            with patch('maeumnarae.views.onboarding_view.find_schools', return_value=[row]):
                await view.search_school()
            choose = next(e for e in client.elements.values() if isinstance(e, ui.button) and e.text.startswith('테스트초등학교 ·'))
            await callback(choose)()
            assert view.fields['neis_school_code'].value == '1234567'
            assert SchoolSettingsRepository(view.database).get().neis_school_code == '1234567'
            view.fields['school_name'].value = '다른학교'
            assert view.fields['neis_school_code'].value == ''
            assert view.step == 'school'
    asyncio.run(check())
