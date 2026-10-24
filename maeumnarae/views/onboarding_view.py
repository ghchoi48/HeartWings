"""비밀번호 → 학교 → 자료 준비 → Welcome 최초 실행 흐름."""

from nicegui import run, ui
from pydantic import ValidationError

from maeumnarae.core.database import Database, DatabaseError
from maeumnarae.core.models import SchoolSettings
from maeumnarae.repositories.onboarding_repo import OnboardingRepository
from maeumnarae.repositories.school_settings_repo import SchoolSettingsRepository
from maeumnarae.services.neis import OFFICES, NeisError, find_schools
from maeumnarae.views.legacy_import_view import LegacyImportView
from maeumnarae.views.roster_import_view import RosterImportView


class OnboardingView:
    def __init__(self, path, on_start, database=None, step='password', settings=None):
        self.path, self.on_start, self.database = path, on_start, database
        self.step = step
        self.settings = settings or SchoolSettings(school_level='초등학교')
        self.busy = False
        self.controls, self.import_views = [], []
        self.import_hosts = {}
        self.built_imports = set()
        self.choosing_school = False

    def button(self, text, callback, **kwargs):
        control = ui.button(text, on_click=callback, **kwargs)
        self.controls.append(control)
        return control

    def build(self):
        with ui.column().classes('w-full max-w-4xl mx-auto px-4 py-8 gap-5'):
            ui.label('마음나래 시작 준비').classes('text-2xl font-bold text-slate-800')
            self.progress = ui.label().classes('text-sm font-semibold text-teal-700')
            self.panels = ui.tab_panels(value=self.step, animated=True, keep_alive=True).props(
                'transition-prev=slide-right transition-next=slide-left'
            ).classes('w-full rounded-2xl shadow-sm')
            with self.panels:
                with ui.tab_panel('password'):
                    ui.icon('lock_outline', size='40px').classes('text-teal-700')
                    ui.label('학생들의 이야기를 안전하게').classes('text-xl font-bold')
                    ui.label('상담 자료를 보호할 DB 비밀번호를 설정해 주세요.')
                    self.password = ui.input('DB 비밀번호', password=True, password_toggle_button=True).props('outlined').classes('w-full')
                    self.confirmation = ui.input('새 DB 비밀번호 확인', password=True, password_toggle_button=True).props('outlined').classes('w-full')
                    self.controls.extend([self.password, self.confirmation])
                    self.button('다음', self.create_database, icon='arrow_forward')
                    self.confirmation.on('keydown.enter', self.create_database)
                with ui.tab_panel('school'):
                    ui.label('학교 정보를 알려주세요').classes('text-xl font-bold')
                    self.fields = {}
                    self.fields['neis_office_code'] = ui.select(OFFICES, value=self.settings.neis_office_code or None, label='교육청')
                    self.fields['school_level'] = ui.select(['초등학교', '중학교', '고등학교'], value=self.settings.school_level, label='학교급')
                    self.fields['school_name'] = ui.input('학교명', value=self.settings.school_name).props('maxlength=100')
                    self.fields['neis_school_code'] = ui.input('학교 나이스 번호', value=self.settings.neis_school_code).props('readonly')
                    self.button('불러오기', self.search_school, icon='search').props('outline')
                    ui.label('검색 결과에서 학교를 선택하면 나이스 번호가 자동 저장됩니다.').classes('text-sm text-slate-500')
                    self.fields['counselor_name'] = ui.input('상담교사 이름', value=self.settings.counselor_name).props('maxlength=100')
                    self.fields['office_number'] = ui.input('사무실 번호', value=self.settings.office_number).props('maxlength=50')
                    for field in self.fields.values():
                        field.props('outlined').classes('w-full')
                        self.controls.append(field)
                    for key in ('neis_office_code', 'school_level', 'school_name'):
                        self.fields[key].on_value_change(self.invalidate_school)
                    ui.label('교육청, 학교명, 상담교사 이름은 필수입니다. 나이스 번호와 사무실 번호는 나중에 설정할 수도 있습니다.').classes('text-sm text-slate-500')
                    self.button('저장하고 다음', self.save_school, icon='arrow_forward')
                with ui.tab_panel('choice'):
                    ui.label('어떻게 자료를 준비할까요?').classes('text-xl font-bold')
                    ui.label('기존 자료를 가져오거나, 바로 시작할 수 있어요.')
                    self.button('울산형 DB 마이그레이션', lambda: self.move('legacy'), icon='drive_folder_upload').classes('w-full')
                    self.button('교사·학생 일괄 등록', lambda: self.move('roster'), icon='group_add').classes('w-full')
                    self.button('건너뛰기', lambda: self.move('welcome'), icon='arrow_forward').props('outline').classes('w-full')
                    self.button('학교 정보로 돌아가기', lambda: self.move('school')).props('flat')
                for step in ('legacy', 'roster'):
                    with ui.tab_panel(step):
                        self.import_hosts[step] = ui.column().classes('w-full')
                        with ui.row().classes('w-full justify-between'):
                            self.button('선택으로 돌아가기', lambda: self.move('choice')).props('flat')
                            self.button('준비 완료 · 다음', lambda: self.move('welcome'), icon='arrow_forward')
                with ui.tab_panel('welcome'):
                    with ui.column().classes('w-full items-center text-center py-12 gap-6'):
                        ui.icon('favorite', size='64px').classes('text-teal-700')
                        ui.label('Welcome! 마음나래에 오신 것을 환영합니다').classes('text-2xl font-bold')
                        ui.label('학생들의 마음에 날개를 더하는 시간, 함께 시작해요.').classes('text-slate-600')
                        ui.label('학교 정보와 자료 가져오기는 설정에서 언제든 이어갈 수 있습니다.').classes('text-sm text-slate-500')
                        self.button('시작하기', self.finish, icon='arrow_forward').classes('px-10 py-2')
                        self.button('자료 준비로 돌아가기', lambda: self.move('choice')).props('flat')
            self.message = ui.label().classes('text-red-700 whitespace-pre-wrap').props('role=alert')
        self.show(self.step)

    def set_busy(self, value):
        self.busy = value
        for control in self.controls:
            control.set_enabled(not value)
        for view in self.import_views:
            view.apply_busy(value)

    def show(self, step):
        self.step = step
        if step in self.import_hosts and step not in self.built_imports:
            with self.import_hosts[step]:
                if step == 'legacy':
                    views = [LegacyImportView(self.database, lambda: self.busy, self.set_busy, self.imported)]
                else:
                    views = [RosterImportView(self.database, kind, lambda: self.busy, self.set_busy, self.imported)
                             for kind in ('teachers', 'students')]
                for view in views:
                    view.build()
                    self.import_views.append(view)
            self.built_imports.add(step)
        self.panels.set_value(step)
        number = {'password': 1, 'school': 2, 'choice': 3, 'legacy': 3, 'roster': 3, 'welcome': 4}[step]
        self.progress.set_text(f'{number} / 4 · ' + {1: 'DB 비밀번호 설정', 2: '학교 정보 입력', 3: '자료 준비', 4: 'Welcome'}[number])
        self.message.set_text('')

    async def move(self, step):
        if self.busy:
            return
        self.set_busy(True)
        try:
            await run.io_bound(OnboardingRepository(self.database).save, step)
            self.show(step)
        except (DatabaseError, ValueError) as error:
            self.message.set_text(str(error))
        finally:
            self.set_busy(False)

    async def create_database(self):
        if self.busy or self.database is not None:
            return
        secret = self.password.value or ''
        if not secret:
            self.message.set_text('비밀번호를 입력해 주세요.')
            return
        if secret != self.confirmation.value:
            self.message.set_text('새 DB의 비밀번호를 다시 확인해 주세요.')
            return
        self.set_busy(True)
        try:
            def create():
                if self.path.exists():
                    raise DatabaseError('DB가 이미 존재합니다. 화면을 새로고침한 뒤 비밀번호로 열어 주세요.')
                database = Database(secret, self.path)
                database.initialize(self.settings, onboarding=True)
                return database
            self.database = await run.io_bound(create)
            self.password.value = self.confirmation.value = ''
            self.show('school')
        except (DatabaseError, ValueError) as error:
            self.message.set_text(str(error))
        finally:
            self.set_busy(False)

    def invalidate_school(self):
        if not self.choosing_school:
            self.fields['neis_school_code'].value = ''

    def school_settings(self):
        return SchoolSettings(neis_api_key=self.settings.neis_api_key,
                              **{key: field.value or '' for key, field in self.fields.items()})

    async def search_school(self):
        if self.busy:
            return
        self.set_busy(True)
        self.message.set_text('')
        try:
            rows = await run.io_bound(find_schools, self.fields['neis_office_code'].value or '',
                                      self.fields['school_name'].value or '', self.settings.neis_api_key)
            rows = [row for row in rows if row.get('SCHUL_KND_SC_NM') == self.fields['school_level'].value]
            if not rows:
                self.message.set_text('일치하는 학교가 없습니다. 교육청, 학교급과 학교명을 확인해 주세요.')
                return
            with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-xl max-h-[80vh] overflow-auto'):
                ui.label('학교 선택').classes('text-xl font-bold')
                ui.label('학교명과 주소를 확인해 주세요. 선택하면 자동 저장됩니다.')
                for row in rows:
                    async def choose(row=row):
                        if self.busy:
                            return
                        self.set_busy(True)
                        try:
                            settings = self.school_settings().model_copy(update={
                                'school_name': row['SCHUL_NM'], 'neis_office_code': row['ATPT_OFCDC_SC_CODE'],
                                'neis_school_code': row['SD_SCHUL_CODE'], 'school_level': row['SCHUL_KND_SC_NM'],
                            })
                            self.settings = await run.io_bound(SchoolSettingsRepository(self.database).save, settings)
                            self.choosing_school = True
                            try:
                                for key, field in self.fields.items():
                                    field.value = getattr(self.settings, key)
                            finally:
                                self.choosing_school = False
                            dialog.close()
                            ui.notify('학교와 나이스 번호를 자동 저장했습니다.', type='positive')
                        except (DatabaseError, ValidationError):
                            ui.notify('학교 정보를 저장하지 못했습니다. 입력 내용을 확인하고 다시 선택해 주세요.', type='negative')
                        finally:
                            self.set_busy(False)
                    ui.button(f"{row['SCHUL_NM']} · {row.get('ORG_RDNMA', '')}", on_click=choose).props('flat align=left').classes('w-full')
                ui.button('닫기', on_click=dialog.close).props('flat')
            dialog.open()
        except NeisError as error:
            self.message.set_text(str(error))
        finally:
            self.set_busy(False)

    async def save_school(self):
        if self.busy:
            return
        if any(not (self.fields[key].value or '').strip() for key in ('neis_office_code', 'school_name', 'counselor_name')):
            self.message.set_text('교육청, 학교명, 상담교사 이름을 입력해 주세요.')
            return
        self.set_busy(True)
        try:
            self.settings = await run.io_bound(SchoolSettingsRepository(self.database).save, self.school_settings())
            await run.io_bound(OnboardingRepository(self.database).save, 'choice')
            self.show('choice')
        except ValidationError:
            self.message.set_text('학교 정보의 입력 길이와 나이스 번호를 확인해 주세요.')
        except DatabaseError as error:
            self.message.set_text(str(error))
        finally:
            self.set_busy(False)

    async def imported(self, kind):
        if kind == 'legacy':
            await self.move('welcome')
        # 교사와 학생은 각각 등록할 수 있도록 현재 단계에 머문다.

    async def finish(self):
        if self.busy:
            return
        self.set_busy(True)
        try:
            await run.io_bound(OnboardingRepository(self.database).save, 'complete')
        except DatabaseError as error:
            self.message.set_text(str(error))
            self.set_busy(False)
            return
        self.on_start(self.database)
