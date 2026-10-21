"""기존 교사 명부를 검색해 연락처와 담당 업무를 확인한다."""

from nicegui import run, ui

from database import DatabaseError


class TeacherSearch:
    kind = 'teacher_search'
    title = '교사 검색'
    icon = 'person_search'

    def __init__(self, home, teachers, instance_id=None, on_change=None):
        self.repository = teachers
        self.generation = 0

    def build(self) -> None:
        with ui.row().classes('w-full items-center flex-nowrap'):
            self.query = ui.input('교사 이름 또는 담당 업무').props('outlined dense').classes('flex-1 min-w-0')
            self.query.on('keydown.enter', self.search)
            ui.button(icon='search', on_click=self.search).props('flat round aria-label="교사 검색 실행"')
        ui.label('검색하면 가장 잘 일치하는 교사 1명을 표시합니다.').classes('text-xs text-slate-400')
        self.results = ui.column().classes('w-full gap-3 max-h-80 overflow-auto')
        with self.results:
            ui.label('교사 이름 또는 담당 업무를 입력해 검색하세요.').classes('text-sm text-slate-400 py-4')

    async def search(self):
        self.generation += 1
        generation = self.generation
        query = (self.query.value or '').strip()
        self.results.clear()
        if not query:
            with self.results:
                ui.label('교사 이름 또는 담당 업무를 입력해 검색하세요.').classes('text-sm text-slate-400 py-4')
            return
        try:
            teachers = await run.io_bound(self.repository.search, query, limit=1)
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
            return
        if generation != self.generation or self.results.is_deleted:
            return
        self.results.clear()
        with self.results:
            if not teachers:
                ui.label('검색 결과가 없습니다. 자문에서 교사를 등록할 수 있습니다.').classes('text-sm text-slate-400 py-4')
            for teacher in teachers:
                with ui.column().classes('w-full gap-1 border-b border-slate-100 pb-3'):
                    ui.label(teacher.name).classes('font-semibold text-slate-800')
                    ui.label(teacher.responsibilities or '담당 업무 미등록').classes('text-sm text-slate-500')
                    ui.label(f'내선 {teacher.extension or "—"} · 연락처 {teacher.contact or "—"}').classes('text-sm text-teal-700 break-all')
