# pyxlsb 1단계 출처 및 기준 동작 검토

검토일: 2026-10-29. 코드 구조·파일 읽기 동작은 변경하지 않고 고지만 추가했습니다.

## 공식 소스 확인

- 버전: pyxlsb 1.0.10
- 작성자: William Turner (`setup.py`, `PKG-INFO`)
- 라이선스: `LGPLv3+`; 배포 메타데이터의 classifier는 LGPL v3 or later
- [공식 PyPI 메타데이터](https://pypi.org/pypi/pyxlsb/1.0.10/json)
- [공식 소스 배포본](https://files.pythonhosted.org/packages/3f/13/eebaeb7a40b062d1c6f7f91d09e73d30a69e33e4baa7cbe4b7658548b1cd/pyxlsb-1.0.10.tar.gz)
- 소스 SHA-256: `8062d1ea8626d3f1980e8b1cfe91a4483747449242ecb61013bc2df85435f685`

다운로드한 소스의 해시는 공식 PyPI 메타데이터와 일치했습니다.
기존 `COPYING`과 `COPYING.LESSER`는 공식 배포본과 바이트 단위로 일치합니다.
원본 파일과 설치된 동일 버전의 아래 세 파일도 바이트 단위로 일치했습니다.

| 원본 파일 | SHA-256 |
|---|---|
| pyxlsb/workbook.py | ed7a699489661b3e39ad6f5cd85a87573e25905c7575b362ab30d9ed626899d7 |
| pyxlsb/worksheet.py | f1574ff31c0fab5c731b284afa2f1a95f91e99a3266a939eaacb90bc059f417d |
| pyxlsb/__init__.py | 639e62d96aeee5af137a8178fe72e67eef9c7ee8f7a0eff413833da215807363 |

이번 단계에서는 공식 소스를 비교용 임시 디렉터리에서만 확인했습니다.
pyxlsb 소스의 저장소 동봉 및 오프라인 다운로드는 아직 구현하지 않았습니다.

## MemoryWorkbook 비교 결과

대상: `maeumnarae/services/data_management/memory_xlsb.py`.
단순 import·상속만을 근거로 삼지 않고 메서드 본문의 처리 순서를 비교했습니다.

| 부분 | 원본과의 관계 | 앱에서 추가·변경된 부분 |
|---|---|---|
| `_parse()` 관계 읽기 | 동일한 ZIP 경로에서 Id→Target을 만들고 시트 관계를 연결 | defusedxml 사용, 딕셔너리 컴프리헨션 |
| `_parse()` workbook 읽기 | SHEET 레코드를 `_sheets`에 추가하고 SHEETS_END에서 중단하는 순서가 동일 | TemporaryFile 복사 대신 ZIP 스트림을 BIFF12Reader에 전달 |
| `_parse()` 문자열 표 | sharedStrings.bin을 StringTable로 읽는 구조가 동일 | ZIP 항목 존재 여부 검사 및 ExitStack으로 수명 관리 |
| `get_sheet()` | 대소문자 무시 이름 검색, 1 기반 인덱스 검사, Worksheet 생성 흐름이 대응 | rels=True 거부, normpath 및 xl/ 경로 검사, ZIP 스트림 사용 |
| `__init__()` | 원본 Workbook 초기화 호출 | streams 보관과 상위 초기화 연결 |
| `open_memory_workbook()` | 원본에는 이 이름의 함수가 없음 | BytesIO·ExitStack·contextmanager 및 finally 정리 조합 |

`_parse()`·`get_sheet()`는 원본 구현을 변경한 파생 부분으로 취급합니다.
나머지 자원 관리·입력 검사는 비교 대상 원본에 없는 앱 추가 부분입니다.
이는 소스 비교에 따른 분류이며 과거 작성 과정이나 독립 창작 사실을 입증하는 기록은 아닙니다.
경계를 명확히 하기 위해 해당 파일 전체에 LGPL-3.0-or-later 고지를 적용합니다.

원본 workbook.py에는 개별 저작권 연도 표기가 없습니다. 패키지 작성자 정보에 근거해
William Turner를 원저작자로 표시했고 임의의 원저작 연도는 만들지 않았습니다.
2026-10-29는 출처·변경 고지를 추가한 날짜이며 기존 구현 변경일은 확인하지 못했습니다.
앱 추가 부분은 Gyuho Choi의 2026년 변경분으로 표시합니다.

`legacy_import.py`는 `convert_date()`를 호출하고 셀 객체를 읽지만, 확인한 날짜 변환
구현은 pyxlsb에 그대로 남아 있습니다. 이번 비교 범위에서는 이 파일에 원본 함수 본문을
복사한 부분을 확인하지 못했으며, 앱 업무 로직의 MIT 라이선스를 유지합니다.

## 기준 동작 및 재실행

`tests/fixtures/legacy_import/`에 직접 만든 합성 XLSB, 생성기, 고정된 baseline.json을
보관합니다. 실제 학생·상담 자료를 사용하지 않았으며 upstream 테스트 파일도 복사하지 않았습니다.
이 자료는 최소 BIFF12/ZIP 읽기 경로용으로 Excel에서 생성한 완전한 문서 호환성 표본은 아닙니다.

실행: `python -m unittest discover -s tests -p 'test_legacy_import_baseline.py' -v`
필요 패키지: pyxlsb 1.0.10, defusedxml, Pydantic 2.x.

- 시트: 인적사항등록, 상담대장
- 제목: 각각 3행·2행; 앞쪽 안내 열 및 제목 주변 공백 포함
- 데이터: 각각 7행·6행; 중간 빈 셀과 생략된 행 위치 보존
- 접수번호·학년도만 있는 상담대장 10행은 기록에서 제외
- 날짜: 59→1900-02-28, 60·61→1900-03-01, 42005→2015-01-01,
  46200·46200.75→2026-06-27; 0·음수·bool·잘못된 문자열 거부
- 날짜 0.5→1900-01-01은 기존 동작으로 기록하며 이 단계에서 수정하지 않음
- 학생 1명·개인 상담 1건, 오류 없음; 전체 모델 결과를 baseline.json에 기록
- 이관 지문: `d0872a7373f2d681a9ab815ff014b129b2d2dfc4d40380586db95d4e779d7c27`
- 중복 제목·누락 제목 거부 및 upstream TemporaryFile 미사용 확인

기준값은 구조 변경 전 현재 구현으로 생성했습니다. 이후 리팩터링에서는 자동으로
기준값을 재생성하지 않고 차이를 검토해야 합니다. 원본 코드와 앱 코드가 바뀐 경우에도
수정본을 사용할 수 있으며 이 테스트는 실행·빌드 차단 장치가 아닙니다.

## 남은 사항

실제 Excel 생성 XLSB의 폭넓은 호환성, 1904 날짜 체계, 모든 손상 파일·자원 제한,
OS별 PyInstaller 결과 및 수정 pyxlsb 재빌드는 이번 단계에서 검증하지 않았습니다.
LGPL 대응 소스·재빌드 자료 제공과 배포 검증은 후속 단계입니다.

## 2단계 — 읽기 경계 분리 (2026-10-29)

1단계 기준 자료를 재생성하지 않고 다음 구조로 변경했습니다.

- `maeumnarae/services/data_management/xlsb_reader.py`: 앱 소유의 MIT 인터페이스.
  `open_workbook(bytes)`는 컨텍스트 관리되는 `WorkbookReader`를 반환합니다.
  `read_sheet(name)`도 컨텍스트 관리자이며, 그 안에서 `SheetRow` 반복자를 사용합니다.
  행 번호는 1 기반이고 값은 A열부터 빈 열을 None으로 보존하는 tuple입니다.
  생략된 행은 만들지 않고 문자열·숫자·bool·None 등 기본 값만 전달합니다.
- `serial_date(int | float)`는 기존 1900 날짜 체계로 date를 반환합니다.
  양수·입력 형식 검사는 기존 업무 함수 `excel_day()`에 남깁니다.
- pyxlsb import와 날짜 변환 호출은 LGPL 파생 파일 `memory_xlsb.py`에 모았습니다.
  기존 MemoryWorkbook은 구현 내부에서 사용하며 앱 읽기 계약에 노출하지 않습니다.
- 파일·ZIP·시트 제한은 읽기 구현으로 옮기고, 제목 확인·행 선별·모델 생성은
  `legacy_import.py`에 유지했습니다. 입력 오류는 기존 ValueError 안내를 유지합니다.
- 구현 교체 시 xlsb_reader의 두 지연 import 대상(open_reader, serial_date)을
  변경합니다. 대체 구현은 크기 제한·메모리 처리·스트림 정리 계약도 충족해야 합니다.
  외부 플러그인 탐색이나 사용자 수정본 차단 장치는 추가하지 않았습니다.

`python -m unittest discover -s tests -v`로 12개 테스트를 통과했습니다.
기존 7개 기준 테스트에 더해, 인터페이스 반환값, 가짜 구현으로 업무 로직 실행,
pyxlsb 없는 상태의 업무 모듈 import, 이동한 크기 제한과 오류 처리,
중도 종료·소비자 오류 시 스트림 정리를 확인했습니다.
소스 동봉·재빌드 자료 제공·OS별 배포 검증은 여전히 후속 단계입니다.

## 3단계 — 원본 및 현재 소스 동봉 (2026-10-29)

앞선 단계의 미완료 항목 중 pyxlsb 소스 동봉과 오프라인 저장을 구현했습니다.
공식 1.0.10 sdist를 `sources/pyxlsb-1.0.10.tar.gz`에 원본 그대로 보관합니다.
`packaging/prepare_pyxlsb_sources.py`가 사용된 pyxlsb 패키지 파일과 앱의 파생 구현,
앱 읽기 계약, 고지·GPL/LGPL·MIT 원문 및 이 기록을 ZIP에 포함합니다.
설치된 라이브러리가 수정본이면 차이를 CHANGES.md에 기록하며 빌드를 차단하지 않습니다.
수정 관찰 날짜와 원래 변경일을 구별하고 추가 수정자의 고지 유지 의무를 안내합니다.
두 PyInstaller spec은 소스 ZIP을 갱신한 뒤 resources/licenses 전체를 동봉합니다.
프로그램 정보에서 기준 원본과 사용 소스를 각각 저장할 수 있습니다.
앱 전체 재빌드 자료 및 실제 OS별 설치본 검증은 아직 후속 단계입니다.

## 4단계 — 재빌드 자료와 릴리스 연결 (2026-10-29)

`BUILDING.md`에 OS별 환경 준비, 로컬 pyxlsb 수정·설치 순서, 개인 서명 키 없이
로컬 앱을 빌드·실행하는 경로와 별도 검증 DB 사용법을 기록했습니다.
`packaging/prepare_local_pyxlsb.py`는 동봉된 실제 소스를 편집 가능한 설치용 폴더로
준비하며 기존 수정본은 덮어쓰지 않습니다.

`scripts/build_desktop.py`는 빌드 입력을 캡처하고 소스·환경이 빌드 중 바뀌지 않았는지
검사한 뒤 OS/CPU별 전체 소스 ZIP, 환경·의존성 기록과 바이너리 대응 해시를 생성합니다.
pyxlsb는 재설치 목록에서 제외하고 사용자가 수정한 로컬 소스를 마지막에 설치합니다.
앱과 리소스를 포함하지만 외부 의존성 전체의 오프라인 미러는 아닙니다.
설치 파일·소스 ZIP·release.json을 함께 배포해야 하며 자동 게시하지 않습니다.
`--sources-only` 산출물은 실행 파일과 대응하지 않는 미검증 자료로 표시합니다.

임시 경로에서 pyxlsb에 확인용 표식을 추가해 오프라인 pip 설치를 수행했고,
그 수정 모듈을 실제로 import하여 합성 XLSB의 기존 이관 지문이 유지됨을 확인했습니다.
사용자 환경의 설치 패키지는 변경하지 않았습니다.
전체 OS별 실행 파일 재빌드·설치·GUI 검증은 여전히 5단계 대상입니다.
