"""마음나래 실행: python main.py (기본: 데스크톱 창)."""

from multiprocessing import freeze_support

if __name__ == '__main__':
    freeze_support()

from maeumnarae.application import main

if __name__ in {'__main__', '__mp_main__'}:
    main()
