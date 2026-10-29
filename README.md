# 마음나래 · HeartWings

**학교 상담의 기록부터 일정과 통계까지, 한곳에서 관리하는 상담 업무 도구입니다.**

마음나래는 전문상담교사의 학교 상담 업무를 돕는 Python 기반 데스크톱 애플리케이션입니다. 학생별 상담 이력, 집단 상담, 교사 자문, 심리검사 등 다양한 기록을 모으고, 캘린더와 통계로 상담 활동을 살펴볼 수 있습니다. 상담 데이터는 사용자의 컴퓨터에 SQLCipher로 암호화하여 저장합니다.

[시작하기](#시작하기) · [주요 기능](#주요-기능) · [빌드 안내](#빌드)

## 주요 기능

| 기능 | 설명 |
| --- | --- |
| 학생 관리 | 학생 인적사항, 학년도별 학적, 상담 타임라인 관리 |
| 상담 기록 | 개인·집단 상담, 교사 자문, 심리검사, 특별교육, 교육·행사 일지 작성 |
| 일지 편집 | 서식 있는 본문 편집 및 저장 전 파일 첨부. 새 일지 저장 시 함께 저장하며 작성 취소 시 임시 첨부파일 폐기 |
| 일정 관리 | 상담 일정과 사용자 일정을 월간·주간 캘린더에서 확인 |
| 통계 및 내보내기 | 기간별 상담 실적 집계, 통계 보고서 및 상담관리 업로드용 XLSX 생성 |
| 명부 및 기존 자료 가져오기 | 학생·교사 XLSX 명부 일괄 등록, 울산형 상담기록관리 XLSB 자료 이관 |
| 맞춤 홈 화면 | 시계, 메모, 할 일, 급식, 날씨, 교사 검색, 미작성 일지 건수, 학교 시정표 위젯 배치 |
| 데이터 관리 | DB 잠금·자동 잠금, 비밀번호 변경, 암호화 백업 및 복원 |

## 시작하기

홈의 **위젯 편집 → 위젯 추가**에서 미작성 일지와 학교 시정표를 추가할 수 있습니다. 미작성 일지는 한국 시각 기준 과거부터 오늘까지의 개인상담·집단상담·자문·특별교육 중 상태가 예약인 건수를 표시합니다. 학교 시정표는 **위젯 편집** 상태에서 시정표 헤더의 **수정 아이콘**으로 교시·시작·종료 시각을 등록하며, 한국 시각 기준으로 현재 교시를 빨간색 계열로 강조합니다. 시정표는 매일 동일하게 적용됩니다.

### 소스에서 실행

홈의 **위젯 편집 → 위젯 추가 → 캘린더**에서 월 달력과 선택일 일정을 볼 수 있습니다. 기존 캘린더의 표시 설정을 공유하며, 사용자 일정은 위젯에서 추가·수정·삭제하고 상담 일정은 해당 기록 편집 화면으로 연결합니다.

**설정 → 일반 → 나이스 연동**에서 NEIS API 인증키와 학교 코드를 저장한 뒤, **캘린더 목록 → 학사일정 (NEIS)**을 체크하면 학교의 학사일정을 월간·주간 캘린더와 홈 캘린더에서 확인할 수 있습니다. 기본적으로 표시가 꺼져 있으며, 선택 여부는 DB에 저장됩니다. 일정은 읽기 전용으로 제공하고 새로고침으로 다시 조회합니다. 인증키 입력란 아래의 **인증키 용도 및 발급 방법**을 펼치면 [나이스 인증키 신청](https://open.neis.go.kr/portal/guide/actKeyPage.do) 안내를 볼 수 있습니다.

저장소를 내려받고 프로젝트 폴더에서 가상환경을 만듭니다. 기존 실행 검증 환경은 **macOS Apple Silicon, Python 3.14**이며, OS별 준비 사항은 [빌드 안내](#빌드)를 참고하세요.

```bash
git clone https://github.com/ghchoi48/HeartWings.git
cd HeartWings
python -m venv .venv
```

가상환경을 활성화합니다.

```bash
# macOS / Linux
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

의존성을 설치하고 앱을 실행합니다.

```bash
python -m pip install -r requirements/desktop.txt
python main.py
```

`python` 명령을 찾을 수 없는 macOS/Linux 환경에서는 가상환경 생성 시 `python3`를 사용하세요.

SQLCipher 드라이버 설치에는 OS·Python·CPU에 맞는 wheel이 필요합니다. wheel이 없으면 SQLCipher와 네이티브 컴파일 환경을 준비해야 합니다. Windows 데스크톱 실행에는 WebView2 Runtime, Linux에는 GTK/WebKit 관련 패키지가 필요합니다.

### 처음 실행할 때

1. 첫 화면에서 사용할 **4글자 이상의 DB 비밀번호와 학교 정보**를 입력합니다.
2. 학생을 등록하거나 XLSX 명부를 가져옵니다. 기존 상담기록관리 자료는 설정의 기존 자료 가져오기 기능으로 가져올 수 있습니다.
3. 상담 일지를 작성하고 캘린더와 통계에서 기록을 확인합니다.
4. **설정 → DB**에서 암호화 백업을 내려받을 수 있습니다.

### 실행 옵션

기본 실행은 데스크톱 창입니다. 브라우저에서 열거나 별도의 DB 파일을 지정할 수도 있습니다.

```bash
# 브라우저 모드: http://127.0.0.1:8080
python main.py --browser --port 8080

# 별도의 DB 파일 사용
python main.py --db ./data/maeumnarae.db
```

두 모드 모두 로컬 주소 `127.0.0.1`에서 실행됩니다. DB는 앱을 처음 열 때 초기화되며, 명령행에서 초기화하거나 열기를 확인하려면 `python init_db.py`를 사용할 수 있습니다.

## 데이터 저장 방식

학생·상담 기록과 첨부파일은 로컬 암호화 DB에 저장합니다. 기본 DB 위치는 다음과 같습니다.

| 운영체제 | 기본 위치 |
| --- | --- |
| macOS | `~/Library/Application Support/maeumnarae/data/maeumnarae.db` |
| Windows | `%LOCALAPPDATA%\maeumnarae\data\maeumnarae.db` |
| Linux | `~/.local/share/maeumnarae/data/maeumnarae.db` (`XDG_DATA_HOME` 설정 시 해당 경로 사용) |

홈 위젯의 메모·할 일·배치는 해당 암호화 DB에 저장되며 DB 백업에도 포함됩니다. 테마·글꼴 같은 화면 설정은 별도의 로컬 JSON 파일에 저장됩니다. 기존 JSON의 위젯 데이터는 업데이트 후 처음 여는 DB로 한 번 이전하고, DB 저장이 완료되면 JSON에서 제거합니다. 여러 DB를 같은 폴더에서 사용했다면 기존 위젯 자료를 보관할 DB를 먼저 여세요.

신규 비밀번호와 변경할 비밀번호는 최소 4글자입니다. 기존의 짧은 비밀번호로 만든 DB도 열 수 있습니다. 업로드 파일은 서버 측 크기 제한 아래 메모리에서 처리하며 평문 임시파일로 저장하지 않습니다. 첨부파일은 파일당 20MB, 한 번에 10개까지, 명부·XLSB 이관 파일은 10MB, DB 복원 파일은 256MB까지 지원합니다. 동시에 한 업로드 요청만 처리합니다.

기존 버전에서 이미 생성된 평문 사본이나 외부 백업까지 자동 삭제하지는 않습니다.

급식·날씨·학교 정보 조회와 새 버전 확인에는 인터넷 연결을 사용합니다. 앱 실행 파일과 사용자 데이터는 별도 위치에 보관되며, DB 백업은 **설정 → DB**에서 관리합니다.

## 빌드

주요 기술은 **Python, NiceGUI, pywebview, SQLCipher**이며, 독립 실행 앱 패키징에는 **PyInstaller**를 사용합니다.

```text
HeartWings/
├── main.py              # 앱 실행
├── init_db.py           # DB 초기화·열기 확인
├── maeumnarae/
│   ├── core/            # DB, 모델, 설정 및 공통 기반
│   ├── repositories/    # 데이터 조회·저장
│   ├── services/        # 외부 연동, 가져오기·내보내기, 백업
│   ├── views/           # 화면 구성
│   └── widgets/         # 홈 위젯
├── resources/           # 아이콘, 글꼴, 서식 및 라이선스
├── requirements/        # 실행·빌드 의존성
├── packaging/           # 번들 설정
└── scripts/             # 앱·리소스 빌드 도구
```

대상 운영체제와 CPU에 맞는 Python 환경에서 빌드합니다.

```bash
python -m pip install -r requirements/build.txt
python scripts/build_desktop.py
```

- **Windows:** x64 Python(Tcl/Tk 포함), Inno Setup 6.3 이상이 필요합니다. `ISCC.exe`를 PATH에 추가하거나 `ISCC_PATH`에 전체 경로를 지정할 수 있습니다. 설치 프로그램은 WebView2 Runtime이 없으면 다운로드하여 설치합니다.
- **macOS:** 대상 CPU의 macOS에서 빌드합니다. 배포 시 필요한 서명·공증은 별도로 진행합니다.
- **Linux:** PyGObject, GTK 3, WebKit2GTK 등 배포판별 패키지와 `pywebview[gtk]`가 필요합니다.

Windows 설치 파일은 `dist/installer/maeumnarae-<버전>-windows-x64-setup.exe`, macOS 산출물은 `dist/마음나래.app` 및 ZIP입니다. Windows/Linux에서 폴더로 배포할 때는 `_internal`을 포함한 `dist/maeumnarae` 전체를 전달합니다.

Windows 설치 버전은 `maeumnarae/core/program_info.py`의 `PROGRAM_VERSION`에서 읽습니다. 버전을 변경한 뒤 다시 빌드하고 새 설치 프로그램으로 업데이트합니다. 앱의 업데이트 알림을 제공하려면 같은 버전의 GitHub Release(예: `v1.1.0`)에 배포 파일을 첨부합니다.

아이콘과 시작 화면은 저장소에 포함되어 있습니다. 이미지를 변경할 때는 `scripts/build_icons.py`, `scripts/build_splash.py`로 재생성할 수 있습니다. 글꼴 변환 절차와 라이선스는 `resources/fonts/`와 `resources/licenses/`에 있습니다.

## 저장소 포함 범위

앱 소스, 빌드 설정·도구, 실행·빌드 의존성, 리소스와 라이선스를 Git에 포함합니다. README와 Git 설정도 유지합니다.

회귀 테스트와 재빌드 안내는 Git에 포함합니다. 미리보기 PDF, 스크린샷, 로그, 가상환경, 사용자 DB, 빌드·배포 산출물은 로컬에 보관하고 Git에서 제외합니다. 새 최상위 경로나 빌드 도구가 필요하면 `.gitignore`의 허용 목록을 함께 갱신하세요. 설치 파일은 GitHub Releases로 배포합니다.

## 라이선스

마음나래는 [MIT 라이선스](LICENSE)로 배포됩니다. 포함된 라이브러리와 글꼴에는 각각의 라이선스가 적용되며, [서드파티 라이선스 안내](resources/licenses/README.md)와 앱의 프로그램 정보 화면에서 확인할 수 있습니다.

배포 구성요소의 고지 범위와 소스 제공 안내는 [서드파티 고지 및 소스 안내](resources/licenses/THIRD_PARTY_NOTICES.md)를 참고하세요. 실제 배포 버전과 전이 의존성은 릴리스별로 확인합니다.

`maeumnarae/services/memory_xlsb.py`는 pyxlsb에서 파생된 구현으로 **LGPL-3.0-or-later**가 적용되며, 프로젝트의 MIT 적용에서 제외됩니다. [출처 및 변경 기록](resources/licenses/pyxlsb/PROVENANCE.md)을 참고하세요.

수정한 pyxlsb로 앱을 재빌드하는 절차와 릴리스 소스 제공 방법은 [BUILDING.md](BUILDING.md)에 있습니다. `scripts/build_desktop.py`는 실행 파일과 대응 소스·환경 기록을 `dist/release/`에 모읍니다.
