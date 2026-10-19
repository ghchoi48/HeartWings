# 마음나래 — 5단계: 네이티브 데스크톱 통합

학교 Wee클래스/전문상담교사를 위한 수동 상담 관리 프로그램의 기반입니다.
현재 **암호화 DB, 데이터 모델, 학생/상담 CRUD와 NiceGUI 학생 관리·상담 일지·캘린더·통계 화면**을 구현했습니다.
홈과 사이드바를 포함한 `main.py`를 네이티브 창으로 실행하며 macOS 앱 번들로 패키징했습니다. AI 기능은 없습니다.
제공된 유튜브 영상은 도구에서 가져오지 못했으므로 영상의 화면/동작은 검증하지 않았습니다.

## 특별교육 페이지

학생을 선택하고 **새 특별 교육**에서 특별교육명, 관련 법령(학교폭력예방법·교원지위법), 사례번호를 입력합니다.
등록한 교육을 선택하면 **특별 교육 일지 목록**에서 일지를 작성·수정할 수 있습니다.
특별교육과 일지는 개인 상담과 별도로 저장되며 기존 DB에 필요한 테이블이 자동으로 추가됩니다.

## 자문 페이지

사이드바의 **자문**을 열면 왼쪽에 교사 목록이 표시됩니다. **교사 추가**에서 이름을 입력해
등록하고, 목록에서 교사를 선택하면 오른쪽에 자문 일지 목록 영역이 표시됩니다.
교사 정보는 목록 아래 **교사 정보 수정**에서 변경할 수 있습니다.
이름·내선번호·담당업무 검색과 페이지 이동을 지원합니다. 자문 일지는 카드형 목록으로 표시되며 **새 자문 일지**와 **열기 / 수정**으로 작성·수정할 수 있습니다.
제목, 날짜·시각, 자문 시간, 상태, 서식 있는 내용과 후속 조치를 교사별로 저장합니다.
연락처·내선번호·담당업무는 선택 입력이며,
기존 DB에도 교사 테이블이 자동으로 추가됩니다.

## 파일 구성

```text
database.py                  # SQLCipher 연결, 트랜잭션, 스키마 버전
models.py                    # 독립적인 Pydantic 입력/응답 모델
repositories/
  student_repo.py            # 학생 CRUD, 이름/학번 검색, 학년 필터
  teacher_repo.py            # 자문 대상 교사 조회 및 저장
  counseling_repo.py         # 상담 CRUD, 학생별 타임라인, 기간 조회
  reporting_repo.py          # 캘린더 조회 및 기간 통계 SQL 집계
  _support.py                # UTC 직렬화, 페이지 크기 검증
init_db.py                   # 1단계 실행/초기화 도구
main.py                      # 네이티브 실행, DB 열기 및 전체 화면 통합
desktop.py                   # 웹뷰 설정, 종료 확인, 오류 로그
maeumnarae.spec               # 전체 데스크톱 앱 PyInstaller 설정
scripts/build_desktop.py      # OS별 빌드 및 macOS ZIP 생성
views/home_view.py           # 홈 안내와 학생 관리 바로가기
views/app_layout.py          # 사이드바와 클라이언트별 화면 전환
views/student_view.py        # 학생 목록/편집 모달/상세 프로필/상담 이력
views/consultation_view.py   # 자문 페이지의 교사 목록/검색/추가/수정
views/counseling_view.py     # 상담 목록/작성/수정/실시간 마크다운 미리보기
views/calendar_view.py       # 월간/주간 캘린더 및 날짜별 일정
views/statistics_view.py     # 기간별 통계와 보고서 다운로드
reporting.py                 # 한국 날짜 범위/보고서 직렬화
tests/                      # 암호화 및 저장소 검증
maeumnarae-data.spec          # 1단계 콘솔 도구의 PyInstaller 설정
requirements.txt
requirements-dev.txt
requirements-desktop.txt     # 네이티브 실행 의존성
requirements-build.txt       # 데스크톱 패키징 의존성
```

## 설치와 실행

Python 3.11 이상을 사용합니다. 대상 Python/OS/CPU에 SQLCipher wheel이 제공되는지 먼저 확인하세요.

```bash
python -m venv .venv
```

macOS/Linux: `source .venv/bin/activate`

Windows PowerShell: `.venv\Scripts\Activate.ps1`

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt -r requirements-desktop.txt
python init_db.py --db ./data/maeumnarae.db
python main.py --db ./data/maeumnarae.db
python -m pytest -q
```

새 DB는 비밀번호를 두 번 입력합니다. 기존 DB는 같은 비밀번호로 다시 열립니다.
명령행 인자, 소스 코드, 설정 파일에 실제 비밀번호를 기록하지 마세요.
비밀번호를 잊으면 복구할 수 없으며 이 단계에 비밀번호 변경/복구 기능은 없습니다.
운영 시 충분히 긴 비밀번호를 사용하고 별도로 관리하세요.

## 학생 관리 화면 실행 (2단계)

```bash
python main.py --db ./data/maeumnarae.db
```

기본은 **네이티브 데스크톱 창**입니다. `--native`를 명시해도 동일합니다.
빈 로컬 포트를 자동 선택하며 서버는 `127.0.0.1`에만 바인딩합니다.
기존 DB를 그대로 사용하며 새 DB라면 화면에서 비밀번호와 확인 값을 입력합니다.
사이드바의 **DB 잠금**은 진행 중인 DB 작업이 끝나면 현재 세션의 키 참조를 해제하고
기존 저장소의 추가 접근을 차단한 뒤 로그인 화면으로 돌아갑니다.
다른 창/탭을 함께 잠그거나 Python 메모리를 완전히 지우는 기능은 아닙니다.
종료할 때 확인 대화상자가 표시되며 창 종료 후 로컬 서버도 종료됩니다.

브라우저 모드가 필요한 경우:

```bash
python main.py --browser --db ./data/maeumnarae.db
# 브라우저 자동 열기 없이 서버만 실행:
python main.py --browser --no-open --port 8081
```

브라우저 기본 주소는 `http://127.0.0.1:8080`입니다. 각 탭은 별도로 비밀번호를 입력합니다.
소스 실행에서는 Python 파일을 저장하면 서버와 화면이 자동으로 다시 로드됩니다.
재시작 후에는 DB 비밀번호를 다시 입력해야 하며, 저장하지 않은 입력은 사라집니다.
PyInstaller로 패키징한 앱에서는 자동 재시작을 끕니다.
네이티브 모드는 pywebview와 OS별 웹뷰 백엔드가 필요합니다. 설치/빌드는 [BUILDING.md](BUILDING.md)를 참고하세요.
오류 로그는 DB 폴더 안 `logs/maeumnarae.log`에 최대 1MB씩 3개를 보관합니다.

- DB를 열면 홈 화면이 표시됩니다. 왼쪽 사이드바에서 `홈`, `학생 관리`, `상담 일지`, `캘린더`, `통계`를 이동합니다.
- 상단 메뉴 버튼으로 사이드바를 접거나 펼칠 수 있습니다. 화면 이동 시 학생 검색/선택 상태를 유지합니다.
- 이름/학번 검색, 학년 필터, 초기화와 20명 단위 이전/다음 페이지를 제공합니다.
- `학생 추가`에서 이름·학년·반을 입력합니다. 학번, 생년월일, 보호자 연락처, 메모는 선택입니다.
- 목록의 선택 버튼으로 학생을 선택하면 상세 프로필과 최신순 상담 타임라인이 표시됩니다.
- `학생 정보 수정`은 같은 편집 모달을 사용하며, 오류 시 입력을 유지하고 연속 저장을 차단합니다.
- 상담 이력은 20건씩 더 볼 수 있으며 예약/완료/취소를 구분합니다. 날짜는 한국 표준시(KST)입니다.
- 이력이 없는 학생에게는 빈 상태 안내를 표시합니다. 상담 신규 작성은 사이드바의 `상담 일지`에서 할 수 있습니다.
- 상담 원문은 안전한 일반 텍스트로 표시합니다. 상담 일지 편집 화면에서는 마크다운 미리보기를 제공합니다.
- 학생 삭제 UI는 이번 단계에 포함하지 않았습니다. 기존 저장소의 삭제 제한은 유지합니다.

화면은 저장소를 주입받으며 SQL을 직접 실행하지 않습니다. DB 작업은
[NiceGUI의 `run.io_bound`](https://nicegui.io/documentation/section_action_events)로 실행하고,
화면 상태는 클라이언트별로 분리합니다. 검색/학생 선택의 늦은 응답은 무시합니다.

`--db` 생략 시 기본 경로는 다음과 같습니다. PyInstaller 임시 폴더나 읽기 전용 앱 번들에는 쓰지 않습니다.

| OS | 기본 위치 |
| --- | --- |
| macOS | `~/Library/Application Support/maeumnarae/data/maeumnarae.db` |
| Windows | `%LOCALAPPDATA%/maeumnarae/data/maeumnarae.db` |
| Linux | `$XDG_DATA_HOME/maeumnarae/data/maeumnarae.db` (기본 `~/.local/share`) |

## 상담 일지 작성 (3단계)

1. 사이드바에서 **상담 일지**를 선택하고 이름/학번으로 학생을 찾습니다.
2. 학생 행을 선택하고 **새 상담 일지**를 누릅니다.
3. 제목, 한국 시각 기준 상담 일시, 소요 시간(1~1440분), 유형, 상태를 입력합니다.
4. 왼쪽 `상담 내용`에 마크다운을 입력하면 오른쪽에 실시간 미리보기가 표시됩니다.
5. 후속 조치를 입력하고 **일지 저장**을 누릅니다. 저장된 일지는 **열기 / 수정**으로 다시 엽니다.

학생/일지 목록은 각각 20개씩 페이지를 이동할 수 있습니다. 새 학생을 등록한 뒤에는 `학생 찾기`를
다시 눌러 조회하세요. 일지는 최신순이며 목록에 일시·예약/완료/취소 상태가 표시됩니다.
새 일지의 기본 상태는 `완료`이고 예약 일정이면 `예약`으로 변경하세요.

학생 관리에서 같은 학생을 열어 둔 경우 저장 직후 상담 타임라인도 갱신합니다.
편집 중 사이드바 이동은 모달이 막으며, `작성 닫기`에서 미저장 변경이 있으면 폐기 여부를 확인합니다.
브라우저 새로고침/종료에 대한 자동 임시 저장은 없습니다. 저장 실패 시에는 입력을 유지하고 재시도할 수 있습니다.
날짜는 한국 시각으로 입력하고 저장소가 UTC로 변환합니다. 마크다운 원문은 변형하지 않습니다.
미리보기는 HTML을 정화하며 원문에 포함된 스크립트/이벤트 핸들러를 실행하지 않습니다.
상담 삭제 UI는 이번 단계 범위에 포함하지 않았습니다.

## 캘린더·통계·보고서 (4단계)

**캘린더**에서 월간/주간 전환, 이전/다음 기간, 오늘, 날짜 직접 이동을 사용할 수 있습니다.
달력은 월요일부터 시작하며 월간 화면의 앞뒤 여백에는 인접 월 날짜가 포함됩니다.
날짜별 건수와 선택 날짜의 시간순 일정을 표시하고, 예약/완료/취소 상태로 필터링할 수 있습니다.
하루 상세 일정은 20건씩 페이지를 이동합니다. 기간 총 건수에는 화면에 표시된 인접 월 날짜도 포함됩니다.
자정을 넘는 상담은 **시작 날짜**에 표시하며, 시간표 겹침 배치나 드래그 변경은 지원하지 않습니다.
`일지 열기`를 누르면 해당 학생의 상담 편집기로 이동합니다. 저장 후 캘린더와 열려 있는 통계가 갱신됩니다.
일정 추가는 상담 일지에서 `예약` 상태로 저장하세요.

**통계**는 시작일과 종료일을 입력하고 `통계 조회`를 누릅니다. 종료일도 포함되며 한국 시각 기준입니다.

| 지표 | 집계 기준 |
| --- | --- |
| 전체 일정 / 상태별 건수 | 기간 내 예약·완료·취소 모두 |
| 완료 상담 / 상담 학생 / 상담 시간 | 완료 상담만, 학생 수는 중복 제외, 시간은 입력된 분 합계 |
| 유형별·월별·학년별 그래프와 표 | 완료 상담만, 학년은 조회 시점의 현재 학생 학년 |

기간 전체를 SQL에서 집계하므로 목록의 1,000건 제한으로 결과를 잘라 계산하지 않습니다.
다만 학적 이력은 아직 저장하지 않아 학생 학년을 수정하면 과거 기간의 학년별 통계도 바뀝니다.
입력 기간을 변경하면 이전 결과와 다운로드를 비활성화하여 잘못된 기간의 보고서 생성을 막습니다.

- **CSV 내보내기**: UTF-8 BOM, 한글/표준 CSV 인용 처리, 수식으로 인식될 수 있는 분류 이름 보호.
- **인쇄용 보고서**: 외부 리소스 없는 HTML을 다운로드합니다. 브라우저에서 열어 인쇄하거나 PDF로 저장할 수 있습니다.
- 두 형식 모두 화면과 같은 집계 스냅샷을 사용하며 학생 이름·학번·상담 제목/본문을 포함하지 않습니다.
- 다운로드 파일 자체는 암호화되지 않습니다. 상세 개인 기록을 내보내는 기능은 이번 단계에 포함하지 않았습니다.

## 데이터 계층 사용 예

다음 코드는 가상 학생을 추가하는 예입니다. 실제 업무 DB에서 반복 실행하지 마세요.

```python
from datetime import datetime, timedelta, timezone
from getpass import getpass
from pathlib import Path

from database import Database
from models import StudentInput, CounselingInput
from repositories.student_repo import StudentRepository
from repositories.counseling_repo import CounselingRepository

db = Database(getpass('DB 비밀번호: '), Path('data') / 'example.db')
db.initialize()
students = StudentRepository(db)
counseling = CounselingRepository(db)

student = students.create(StudentInput(name='가상 학생', grade=1, classroom='2'))
entry = counseling.create(CounselingInput(
    student_id=student.id,
    starts_at=datetime(2026, 10, 15, 10, tzinfo=timezone(timedelta(hours=9))),
    title='학교 적응 상담',
    status='completed',
    content_markdown='## 상담 내용\n학생이 직접 이야기한 내용을 수동 기록합니다.',
))
timeline = counseling.list(student_id=student.id)
```

- `create(input)` / `get(id)` / `list(...)` / `update(id, input)` / `delete(id)`를 제공합니다.
- 수정은 입력 필드 전체 교체입니다. `get`은 없으면 `None`, 없는 ID 수정/삭제는 `NotFoundError`입니다.
- 학번은 선택 항목이며, 입력된 학번은 유일합니다. 이름은 중복을 허용합니다.
- 상담이 연결된 학생 삭제와 없는 학생의 상담 등록은 `ConflictError`입니다. 자동 연쇄 삭제는 없습니다.
- 기간 조회는 상담 **시작 시각** 기준 `[start, end)`입니다. 시간대가 있는 datetime을 받아 UTC로 저장합니다.
- 일정 상태는 `scheduled`, `completed`, `cancelled`입니다. 학년은 초·중·고를 포괄하는 1~12 범위입니다.
- 목록은 기본 100개, 최대 1,000개입니다. `offset`으로 다음 페이지를 조회하세요.
- 각 작업은 별도 연결 및 트랜잭션을 사용하며 실패 시 롤백하고 항상 닫습니다.
- UI는 저장소만 호출하며, 키 유도/파일 I/O는 백그라운드 I/O 실행 경로에서 처리합니다.

## 암호화와 운영 범위

SQLCipher로 DB 전체를 암호화합니다. `cipher_version` 및 실제 스키마 읽기를 검사하며,
드라이버 누락/평문 SQLite/잘못된 키에서 평문으로 전환하거나 기존 파일을 지우지 않습니다.
비밀번호는 실행 중 메모리에 존재합니다. 암호화는 잠금 해제된 앱의 메모리나 내보낸 보고서까지 보호하지 않습니다.
키 설정은 [SQLCipher 공식 API](https://www.zetetic.net/sqlcipher/sqlcipher-api/)를 따릅니다.

마크다운은 원문 그대로 저장하며 미리보기는 NiceGUI의 HTML 정화 기능(`sanitize=True`)을 사용합니다.
백업 UI는 후속 단계 범위입니다. 현재는 앱의 모든 연결을 닫고 암호화 DB 파일을 안전한 곳에 복사하세요.
이 단계는 실사용 완성 앱이 아니며 자동 잠금, 접근 기록, 백업/복구 UI는 아직 없습니다.

## 크로스 플랫폼 패키징

```bash
python -m pip install -r requirements-build.txt
python scripts/build_desktop.py
```

macOS 결과는 `dist/마음나래.app`, 배포 압축본은 `dist/maeumnarae-macos.zip`입니다.
Windows/Linux는 `dist/maeumnarae/` 폴더 전체를 배포합니다. 실행 파일만 분리하지 마세요.
실행 및 OS별 의존성, 서명, 검증 범위는 [BUILDING.md](BUILDING.md)에 정리했습니다.
`maeumnarae-data.spec`은 별도 1단계 콘솔 도구용으로 남겨 두었습니다.

[PyInstaller 공식 문서](https://pyinstaller.org/en/stable/operating-mode.html)에 따라
Windows 앱은 Windows, macOS 앱은 macOS, Linux 앱은 Linux에서 각각 빌드해야 합니다.
CPU 아키텍처도 대상과 맞추세요. 하나의 빌드 산출물이 세 OS에서 실행되지는 않습니다.

[sqlcipher3 공식 설치 안내](https://github.com/coleifer/sqlcipher3)에 따르면 0.6.2부터
SQLCipher를 포함한 wheel을 제공합니다. 다만 대상 OS/CPU/Python에 맞는 wheel 제공 여부는 별도로 확인해야 합니다.
소스 빌드가 필요한 환경에서는 해당 릴리스의 vendor 소스/컴파일러 요구사항을 따라야 합니다.
다른 배포본인 `sqlcipher3-binary`, `pysqlcipher3`를 같은 환경에 혼합 설치하지 마세요.
현재 코드는 `sqlcipher3.dbapi2`만 사용하며 로딩 실패 시 명확한 오류로 중단합니다.

spec은 SQLCipher 확장 모듈과 패키지 리소스를 수집합니다. 동적 라이브러리를 사용하는 자체 빌드는
DLL/dylib/so의 전이 의존성(OpenSSL 등)까지 포함했는지 확인하고, 누락 항목은 `binaries`에 추가하세요.
평문 SQLite 라이브러리를 SQLCipher 대신 번들하지 마세요. macOS는 서명/공증,
Linux는 배포 환경의 glibc 및 후속 GUI 백엔드, Windows는 DLL 아키텍처를 별도로 검증해야 합니다.
빌드 후 Python이 설치되지 않은 대상 컴퓨터에서 DB 생성, 재열기, 잘못된 비밀번호 거부를 확인하세요.
운영 데이터나 비밀번호는 빌드 입력에 포함하지 않습니다.

## 검증 현황

2026-10-15 macOS arm64 / Python 3.14에서 실제 실행 검증을 완료했습니다.
프로젝트 가상환경에 NiceGUI 3.18.0, SQLCipher 드라이버 sqlcipher3 0.6.4,
Pydantic 2.14.1을 설치했습니다. 이전의 설치/포트 제한은 실행 권한 검토 후 해소되었습니다.

- `python -m pytest -q`: 25개 및 입력 검증 하위 사례 7개 통과 (실제 SQLCipher CRUD·암호화·잘못된 키 거부 포함)
- `main.py`를 로컬 포트 8765에서 실행하고 별도 임시 암호화 DB로 Chrome에서 검증
- DB 생성/열기 → 홈 → 학생 추가/상세 → 수정 → 검색 → 사이드바 이동 확인
- 페이지를 다시 열어 잘못된 비밀번호 거부, 올바른 비밀번호로 재열기 및 수정 내용 보존 확인
- 실제 실행에서 발견한 수정 모달의 중복 삭제 오류를 수정하고 전체 브라우저 흐름 재검증
- 수정 후 브라우저 JavaScript 오류 및 서버 작업 오류 없음
- 상담 일지: 작성/수정, 실시간 미리보기, 위험한 HTML 정화, 미저장 취소, 타임라인 갱신 및 DB 재열기 후 원문 보존 검증
- 캘린더 월간/주간 전환, 일지 연결·저장 후 갱신, 실제 CSV/HTML 다운로드를 Chrome에서 검증
- 한국 시각 월말/자정 경계, 1,005건 집계, 중복 학생 수 및 예약/취소 구분을 SQLCipher에서 검증
- 화면 캡처: `artifacts/home.png`, `artifacts/student.png`, `artifacts/counseling-editor.png`, `artifacts/calendar.png`, `artifacts/statistics.png`

```bash
python -m pytest -q
```

브라우저 검증은 설치된 Google Chrome과 별도 Playwright 패키지를 사용합니다.
아래 테스트는 가상 학생을 실제로 저장하므로 반드시 전용 테스트 DB로 실행하세요.
테스트용 비밀번호는 스크립트 안의 공개된 테스트 값이며 운영용으로 사용하면 안 됩니다.

```bash
python -m pip install playwright
python main.py --browser --no-open --db /tmp/maeumnarae-browser-test.db --port 8765
# 다른 터미널에서 같은 가상환경으로 실행:
python tests/browser_smoke.py
```

macOS arm64에서 소스의 네이티브 창과 PyInstaller `.app`을 실제 실행했습니다.
학생 입력/수정 보존, DB 잠금·재로그인, 네이티브 CSV 저장 대화상자 및 파일 저장, 종료 후 서버 정리를 확인했습니다.
Windows/Linux 및 다른 컴퓨터에서의 실행은 아직 검증하지 않았습니다.

## 구현 완료 범위

2단계 완료: 학생 테이블, 추가/수정 모달, 프로필과 상담 타임라인.

3단계 완료: 상담 일지 작성/수정, 마크다운 편집/프리뷰와 저장.

4단계 완료: 월간/주간 캘린더, 통계 및 CSV/인쇄용 HTML 보고서 내보내기.

5단계 완료: 전체 기능 통합, 수동 DB 잠금, 네이티브 실행 기본값, macOS 앱 패키징과 실제 실행 검증.

## 학생 목록 재사용

`views/student_list.py`의 `StudentList`는 목록 카드, 검색, 이름순 정렬,
페이지 이동과 데이터 조회를 제공합니다. 페이지/클라이언트마다 새 인스턴스를 만드세요.

```python
from views.student_list import StudentList

# 페이지의 UI 컨테이너 안에서 생성합니다.
# students는 StudentRepository, on_student_selected는 학생 ID를 받는 함수입니다.
student_list = StudentList(students, on_select=on_student_selected, page_size=10)
student_list.build()  # 최초 목록 조회도 자동 실행
```

선택 콜백은 일반 함수와 async 함수를 모두 지원합니다. 데이터 변경 후에는
`await student_list.reload()`로 갱신합니다. 최초 조회를 직접 제어하려면
`build(autoload=False)`를 사용한 뒤 `reload()`를 호출하세요.
