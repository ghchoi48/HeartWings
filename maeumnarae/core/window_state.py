"""Windows 창의 일반 상태 외곽 좌표와 최대화 여부를 저장한다."""

import logging
from pathlib import Path

from maeumnarae.core.settings_store import SettingsStore


def read_window_state(store: SettingsStore) -> dict | None:
    try:
        state = store.read().get('window')
        if not isinstance(state, dict):
            return None
        for key in ('x', 'y', 'width', 'height'):
            if type(state.get(key)) is not int or not -1_000_000 < state[key] < 1_000_000:
                return None
        if state['width'] <= 0 or state['height'] <= 0 or type(state.get('maximized')) is not bool:
            return None
        return state
    except (OSError, ValueError):
        logging.getLogger('nicegui').warning('창 설정을 읽지 못해 기본 위치로 시작합니다.', exc_info=True)
        return None


def visible_window_state(saved: dict | None, work_areas) -> dict | None:
    """이전 모니터의 제목 표시줄을 잡을 수 없으면 최대화 상태도 버린다."""
    if saved is None:
        return None
    for x, y, width, height in work_areas:
        visible_width = min(saved['x'] + saved['width'], x + width) - max(saved['x'], x)
        if visible_width >= 96 and y <= saved['y'] and saved['y'] + 32 <= y + height:
            return saved
    return None


def install_window_state(window, path: Path, fit) -> None:
    store = SettingsStore(path)
    saved = read_window_state(store)

    def before_show():
        from System.Windows.Forms import FormWindowState, Screen

        form = window.native
        areas = [screen.WorkingArea for screen in Screen.AllScreens]
        restored = visible_window_state(saved, [(a.X, a.Y, a.Width, a.Height) for a in areas])
        if saved is not None and restored is None:
            logging.getLogger('nicegui').warning(
                '저장된 창 위치가 현재 화면 밖에 있어 기본 위치로 시작합니다: %s', path)
        fit(window, restored)
        maximized = bool(restored and restored['maximized'])

        def resized(sender, event):
            nonlocal maximized
            if form.WindowState != FormWindowState.Minimized:
                maximized = form.WindowState == FormWindowState.Maximized

        def closing(sender, event):
            # pywebview의 종료 확인 처리 뒤에 실행되므로 취소한 종료는 저장하지 않는다.
            if event.Cancel:
                return
            bounds = form.Bounds if form.WindowState == FormWindowState.Normal else form.RestoreBounds
            state = dict(x=int(bounds.X), y=int(bounds.Y), width=int(bounds.Width),
                         height=int(bounds.Height), maximized=maximized)
            try:
                # 전용 파일이므로 손상된 이전 JSON도 다음 정상 종료 때 복구한다.
                store.path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    store.read()
                except ValueError:
                    store.path.write_text('{}', encoding='utf-8')
                store.update(lambda data: data.update(window=state))
            except (OSError, ValueError):
                logging.getLogger('nicegui').warning('창 설정을 저장하지 못했습니다.', exc_info=True)

        form.Resize += resized
        form.FormClosing += closing
        if maximized:
            form.WindowState = FormWindowState.Maximized

    window.events.before_show += before_show
