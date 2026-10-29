"""앱의 XLSB 읽기 계약. 구현 교체 지점은 이 모듈의 지연 import 두 곳이다.

매크로/수식은 실행하지 않고 저장된 값만 읽는다. 구현은 크기 제한을 검사하고
컨텍스트 종료 시 스트림을 닫아야 한다. 라이브러리 객체를 외부에 반환하지 않는다.
"""
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Iterator, Protocol

MAX_BYTES = 10 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 512
MAX_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
MAX_ROWS = 20000
MAX_COLUMNS = 100

CellValue = str | int | float | bool | None


@dataclass(frozen=True)
class SheetRow:
    """number는 1 기반 원본 행 번호, values는 A열부터 빈 열을 None으로 보존한다."""
    number: int
    values: tuple[CellValue, ...]


class WorkbookReader(Protocol):
    def read_sheet(self, name: str) -> AbstractContextManager[Iterator[SheetRow]]:
        """저장된 행을 순서대로 반환한다. 생략된 행을 새로 만들지 않는다."""
        ...


@contextmanager
def open_workbook(content: bytes) -> Iterator[WorkbookReader]:
    from maeumnarae.services.memory_xlsb import open_reader

    try:
        with open_reader(content) as reader:
            yield reader
    except ValueError:
        raise
    except Exception:
        raise ValueError('XLSB 파일을 읽지 못했습니다. 두 시트와 파일 형식을 확인하세요.') from None


def serial_date(value: int | float) -> date:
    """기존 1900 날짜 체계의 변환 결과를 유지한다. 입력 검증은 호출자가 담당한다."""
    from maeumnarae.services.memory_xlsb import serial_date as convert

    return convert(value)
