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


def install_window_state(window, path: Path, fit) -> None:
    store = SettingsStore(path)
    saved = read_window_state(store)

    def before_show():
        from System.Windows.Forms import FormWindowState

        form = window.native
        fit(window, saved)
        maximized = bool(saved and saved['maximized'])

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
