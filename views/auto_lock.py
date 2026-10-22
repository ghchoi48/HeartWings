"""클라이언트별 미조작 시간 감지와 DB 자동 잠금."""

import logging
import math
import time
from collections.abc import Awaitable, Callable

from nicegui import ui

from settings_store import SettingsStore

AUTO_LOCK_MINUTES = (5, 10, 20, 30, 40, 50, 60)
DEFAULT_AUTO_LOCK_MINUTES = 20


class AutoLock:
    def __init__(self, store: SettingsStore, on_lock: Callable[[], Awaitable[None]],
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.on_lock = on_lock
        self.clock = clock
        self.minutes = DEFAULT_AUTO_LOCK_MINUTES
        try:
            value = store.read().get('auto_lock_minutes')
            if type(value) is int and value in AUTO_LOCK_MINUTES:
                self.minutes = value
        except (OSError, ValueError, TypeError):
            logging.getLogger(__name__).warning('자동 잠금 설정을 읽을 수 없어 기본값을 사용합니다.')
        self.last_activity = clock()
        self.locked = False
        self.label = None
        self.timer = None

    @property
    def remaining(self) -> int:
        return max(0, math.ceil(self.minutes * 60 - (self.clock() - self.last_activity)))

    def update_label(self) -> None:
        if self.label is not None:
            minutes, seconds = divmod(self.remaining, 60)
            self.label.set_text(f'자동 잠금 {minutes:02d}:{seconds:02d}')

    async def activity(self) -> None:
        if self.locked:
            return
        # 절전/연결 복구 후 도착한 입력으로 이미 지난 잠금 시한을 연장하지 않는다.
        if self.remaining == 0:
            await self.lock()
            return
        self.last_activity = self.clock()
        self.update_label()

    async def tick(self) -> None:
        if self.locked:
            return
        self.update_label()
        if self.remaining == 0:
            await self.lock()

    async def lock(self) -> None:
        if self.locked:
            return
        self.locked = True
        if self.timer is not None:
            self.timer.deactivate()
        await self.on_lock()

    async def change_minutes(self, value) -> None:
        if type(value) is not int or value not in AUTO_LOCK_MINUTES or self.locked:
            return
        await self.activity()
        if self.locked:
            return
        self.minutes = value
        self.update_label()
        try:
            self.store.update(lambda data: data.update(auto_lock_minutes=value))
        except (OSError, ValueError):
            ui.notify('자동 잠금 시간은 적용했지만 설정을 저장하지 못했습니다. 저장 폴더의 권한을 확인해 주세요.',
                      type='negative')

    def build_controls(self) -> None:
        ui.select({minutes: f'{minutes}분' for minutes in AUTO_LOCK_MINUTES},
                  value=self.minutes, label='자동 잠금까지의 시간',
                  on_change=lambda e: self.change_minutes(e.value)).props('outlined').classes('w-full')
        ui.label('기본값은 20분이며, 변경 사항은 즉시 적용되고 자동으로 저장됩니다.').classes('text-sm text-slate-500')

    def install(self) -> None:
        self.last_activity = self.clock()
        self.label = ui.label().classes('text-sm tabular-nums whitespace-nowrap').props(
            'aria-label="자동 잠금까지 남은 시간"')
        self.label.tooltip('마우스, 키보드, 터치 또는 스크롤 조작 시 시간이 다시 시작됩니다.')
        self.update_label()
        ui.on('app_user_activity', self.activity, args=[], throttle=0.25)
        ui.run_javascript('''
            (() => {
                window.appActivityController?.abort();
                const controller = new AbortController();
                window.appActivityController = controller;
                const report = event => {
                    if (event.isTrusted) emitEvent('app_user_activity');
                };
                for (const name of ['pointerdown', 'pointermove', 'keydown', 'input', 'wheel', 'touchstart', 'touchmove']) {
                    document.addEventListener(name, report,
                        {capture: true, passive: true, signal: controller.signal});
                }
            })();
        ''')
        # 서버 타이머이므로 백그라운드 탭의 JavaScript 타이머 제한에 영향받지 않는다.
        self.timer = ui.timer(1, self.tick)
