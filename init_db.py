"""1단계 데이터 계층의 수동 실행 도구. 비밀번호는 터미널에서만 입력한다."""

import argparse
from getpass import getpass
from pathlib import Path

from database import Database, DatabaseError, default_database_path


def main() -> int:
    """새 DB를 초기화하거나 기존 DB의 암호와 스키마 버전을 확인한다."""
    parser = argparse.ArgumentParser(description='마음나래 암호화 DB 초기화/확인')
    parser.add_argument('--db', type=Path, default=default_database_path())
    args = parser.parse_args()
    try:
        password = getpass('DB 비밀번호: ')
        if not args.db.exists() and password != getpass('새 비밀번호 확인: '):
            parser.error('비밀번호가 일치하지 않습니다.')
        Database(password, args.db).initialize()
    except (DatabaseError, ValueError) as error:
        print(str(error))
        return 1
    print(f'암호화 DB 준비 완료: {args.db.resolve()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
