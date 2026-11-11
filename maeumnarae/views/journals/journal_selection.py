"""인라인 에디터에서 편집 중인 일지 카드의 선택 표시."""

from nicegui import ui


class JournalSelection:
    def __init__(self):
        self.selected_id: int | None = None
        self.rows: dict[int, ui.row] = {}

    def register(self, entry_id: int, row: ui.row) -> None:
        self.rows[entry_id] = row
        self._update(entry_id, row)

    def select(self, entry_id: int | None) -> None:
        self.selected_id = entry_id
        for row_id, row in self.rows.items():
            if not row.is_deleted:
                self._update(row_id, row)

    def _update(self, entry_id: int, row: ui.row) -> None:
        selected = entry_id == self.selected_id
        row.classes(add='app-primary-soft' if selected else '',
                    remove='' if selected else 'app-primary-soft')
        row.props(f'aria-pressed="{str(selected).lower()}"')
