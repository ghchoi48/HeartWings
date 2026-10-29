"""마음나래 실행: python main.py (기본: 데스크톱 창)."""

import sys

# 배포 검증은 GUI/DB/서버를 시작하지 않고 실제 번들의 모듈·리소스를 사용한다.
if __name__ == '__main__' and '--verify-distribution' in sys.argv:
    from maeumnarae.core.distribution_check import main as verify_distribution
    raise SystemExit(verify_distribution())

from maeumnarae.core.startup import configure_startup_output

configure_startup_output()

from maeumnarae.core.splash import configure_splash

configure_splash()

# frozen 자식은 freeze_support()에서 바로 실행되므로 등록을 먼저 끝낸다.
# spawn 진입점을 등록하되 이 시점에는 서버를 실행하지 않는다.
from maeumnarae.core.desktop import register_native_icon, register_native_startup_guard

register_native_icon()
register_native_startup_guard()

from multiprocessing import freeze_support

if __name__ == '__main__':
    freeze_support()

from maeumnarae.application import main

if __name__ in {'__main__', '__mp_main__'}:
    main()
