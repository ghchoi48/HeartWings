"""다른 화면에서 재사용하는 학생 목록 카드, 검색 및 페이지 이동."""

from collections.abc import Awaitable, Callable
from inspect import isawaitable

from nicegui import events, run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.repositories.students.student_repo import StudentRepository


class StudentList:
    """페이지/클라이언트마다 생성하며 선택한 학생 ID를 콜백에 전달한다."""

    def __init__(self, students: StudentRepository,
                 on_select: Callable[[int], Awaitable[None] | None] | None = None,
                 *, page_size: int = 10):
        self.students = students
        self.on_select = on_select
        self.page_size = page_size
        self.list_request = 0
        self.has_special_education_logs = False

    def build(self, *, autoload: bool = True,
              special_education_filter: bool = False,
              on_add: Callable[[], Awaitable[None] | None] | None = None) -> None:
        """현재 컨테이너에 목록 카드를 만들고 기본적으로 최초 조회를 예약한다."""
        with ui.card().classes('w-full h-full min-w-0 rounded-2xl shadow-sm p-5'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('학생 목록').classes('text-xl font-bold')
                if on_add is not None:
                    ui.button('학생 추가', icon='person_add', on_click=on_add)
            columns = [
                {'name': name, 'label': label, 'field': name, 'align': 'left'}
                for name, label in [('name', '이름'), ('nickname', '별명'), ('gender', '성별'), ('grade', '학년'), ('classroom', '반')]
            ]
            self.table = ui.table(columns=columns, rows=[], row_key='id', pagination={
                'rowsPerPage': self.page_size, 'sortBy': 'name', 'descending': False, 'page': 1,
            }).classes('w-full').props(
                'flat :rows-per-page-options="[10, 20, 30]" rows-per-page-label="페이지당 학생 수" '
                'no-data-label="등록된 학생이 없습니다" no-results-label="검색 결과가 없습니다"')
            with self.table.add_slot('top'):
                search = ui.input('학생 검색', placeholder='이름, 별명, 성별, 학년, 반').props(
                    'outlined dense clearable debounce=300').classes('w-full').bind_value(self.table, 'filter')
                if special_education_filter:
                    with search.add_slot('append'):
                        ui.checkbox('일지가 있는 학생만',
                                    on_change=self._change_special_education_filter).props(
                                        'dense').classes('text-xs').on('click.stop', lambda: None)
            self.table.on('rowClick', self._select_student,
                          js_handler='(event, row) => emit(row.id)')
        if autoload:
            ui.timer(0.01, self.reload, once=True)

    async def reload(self) -> None:
        """전체 목록을 적재하고 검색과 페이지 이동은 표에 맡긴다. 늦은 응답은 무시한다."""
        self.list_request += 1
        request = self.list_request
        self.table.rows = []
        self.table.props('loading')
        try:
            students = []
            while True:
                batch = await run.io_bound(
                    self.students.list, limit=1000, offset=len(students),
                    has_special_education_logs=self.has_special_education_logs)
                if request != self.list_request:
                    return
                students.extend(batch)
                if len(batch) < 1000:
                    break
        except DatabaseError as error:
            if request == self.list_request:
                ui.notify(str(error), type='negative')
            return
        finally:
            if request == self.list_request:
                self.table.props(remove='loading')
        if request != self.list_request:
            return
        self.table.rows = [dict(id=s.id, name=s.name, nickname=s.nickname or '—',
                                gender=s.gender or '—', grade=s.grade, classroom=s.classroom) for s in students]
        self.table.update()

    async def _change_special_education_filter(self, event: events.ValueChangeEventArguments) -> None:
        self.has_special_education_logs = bool(event.value)
        self.table.pagination['page'] = 1
        self.table.props('no-data-label="조건에 맞는 학생이 없습니다"' if event.value
                         else 'no-data-label="등록된 학생이 없습니다"')
        await self.reload()

    async def _select_student(self, event: events.GenericEventArguments) -> None:
        if self.on_select is not None:
            result = self.on_select(event.args)
            if isawaitable(result):
                await result
