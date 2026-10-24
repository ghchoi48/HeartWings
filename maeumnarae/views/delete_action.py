"""삭제 확인, 중복 실행 방지 및 오류 표시를 공유한다."""

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.repositories.deletion_repo import DeletionRepository, TARGETS


def delete_button(database, kind, record, on_deleted, *, blocked=lambda: False, icon_only=False):
    """record는 클릭 시점의 모델을 반환하며, 확인 후에도 해당 ID만 삭제한다."""
    busy = False

    async def remove():
        nonlocal busy
        if busy:
            return
        item = record()
        if item is None:
            ui.notify('삭제할 항목을 먼저 선택해 주세요.', type='warning')
            return
        if blocked():
            ui.notify('작성 중인 내용을 저장하거나 편집을 닫은 후 삭제해 주세요.', type='warning')
            return
        busy = True
        button.disable()
        dialog = None
        try:
            _, label, impact = TARGETS[kind]
            with ui.context.client.content:
                with ui.dialog().props('persistent') as dialog, ui.card().classes('max-w-lg p-6'):
                    ui.label(f'{label} 삭제').classes('text-xl font-bold')
                    ui.label(f'“{getattr(item, "name", None) or item.title}”을(를) 삭제할까요?').classes('break-words')
                    if impact:
                        ui.label(impact)
                    if kind != 'event':
                        ui.label('삭제되는 일지에 연결된 첨부파일도 함께 삭제됩니다.')
                    ui.label('삭제한 데이터는 되돌릴 수 없습니다.').classes('text-red-700')
                    with ui.row().classes('w-full justify-end'):
                        ui.button('취소', on_click=lambda: dialog.submit(False)).props('flat')
                        ui.button('삭제 확인', on_click=lambda: dialog.submit(True)).props('color=negative')
            if not await dialog:
                return
            await run.io_bound(DeletionRepository(database).delete, kind, item.id)
            ui.notify(f'{label}을(를) 삭제했습니다.', type='positive')
            await on_deleted()
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
        finally:
            busy = False
            if not button.is_deleted:
                button.enable()
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()

    label = f'{TARGETS[kind][1]} 삭제'
    if icon_only:
        button = ui.button(icon='delete_outline').props(
            f'flat round color=negative aria-label="{label}"').tooltip(label)
        button.on('click.stop', remove)
    else:
        button = ui.button(label, icon='delete_outline', on_click=remove).props('flat color=negative')
    return button
