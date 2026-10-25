# 마음나래 · HeartWings

**학교 상담의 기록부터 일정과 통계까지, 한곳에서 관리하는 상담 업무 도구입니다.**

마음나래는 전문상담교사의 학교 상담 업무를 돕는 Python 기반 데스크톱 애플리케이션입니다. 학생별 상담 이력, 집단 상담, 교사 자문, 심리검사 등 다양한 기록을 모으고, 캘린더와 통계로 상담 활동을 살펴볼 수 있습니다. 상담 데이터는 사용자의 컴퓨터에 SQLCipher로 암호화하여 저장합니다.

[시작하기](#시작하기) · [주요 기능](#주요-기능) · [자료 이관 안내](docs/legacy-import.md) · [개발 및 빌드](docs/building.md)

## 주요 기능

| 기능 | 설명 |
| --- | --- |
| 학생 관리 | 학생 인적사항, 학년도별 학적, 상담 타임라인 관리 |
| 상담 기록 | 개인·집단 상담, 교사 자문, 심리검사, 특별교육, 교육·행사 일지 작성 |
| 일지 편집 | 서식 있는 본문 편집 및 저장 전 파일 첨부. 새 일지 저장 시 함께 저장하며 작성 취소 시 임시 첨부파일 폐기 |
| 일정 관리 | 상담 일정과 사용자 일정을 월간·주간 캘린더에서 확인 |
| 통계 및 내보내기 | 기간별 상담 실적 집계, 통계 보고서 및 상담관리 업로드용 XLSX 생성 |
| 명부 및 기존 자료 가져오기 | 학생·교사 XLSX 명부 일괄 등록, 울산형 상담기록관리 XLSB 자료 이관 |
| 맞춤 홈 화면 | 시계, 메모, 할 일, 급식, 날씨, 교사 검색 위젯 배치 |
| 데이터 관리 | DB 잠금·자동 잠금, 비밀번호 변경, 암호화 백업 및 복원 |

## 시작하기

### 소스에서 실행

저장소를 내려받고 프로젝트 폴더에서 가상환경을 만듭니다. 기존 실행 검증 환경은 **macOS Apple Silicon, Python 3.14**이며, OS별 준비 사항은 [실행 및 빌드 안내](docs/building.md)를 참고하세요.

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

SQLCipher 드라이버 설치에는 OS·Python·CPU에 맞는 wheel 또는 네이티브 빌드 환경이 필요합니다. 설치가 실패하면 [SQLCipher 의존성 안내](docs/building.md#sqlcipher-네이티브-의존성)를 확인하세요. Windows 데스크톱 실행에는 WebView2 Runtime, Linux에는 GTK/WebKit 관련 패키지가 필요합니다.

### 처음 실행할 때

1. 첫 화면에서 사용할 **DB 비밀번호와 학교 정보**를 입력합니다.
2. 학생을 등록하거나 XLSX 명부를 가져옵니다. 기존 상담기록관리 자료가 있다면 [XLSB 이관 안내](docs/legacy-import.md)를 따라 가져올 수 있습니다.
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

화면 설정과 홈 위젯의 메모·할 일 등은 암호화 DB와 별도의 로컬 JSON 파일에 저장됩니다. 민감한 상담 내용은 상담 일지에 기록하세요.

급식·날씨·학교 정보 조회와 새 버전 확인에는 인터넷 연결을 사용합니다. 앱 실행 파일과 사용자 데이터는 별도 위치에 보관되며, DB 백업은 **설정 → DB**에서 관리합니다.

## 개발 안내

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
├── requirements/        # 실행·개발·빌드 의존성
├── packaging/           # 번들 설정
├── scripts/             # 빌드 자동화
├── tests/               # 테스트
└── docs/                # 상세 문서
```

개발 의존성 설치 및 테스트:

```bash
python -m pip install -r requirements/dev.txt
python -m pytest
```

DB 통합 테스트에는 SQLCipher가 필요합니다. 데스크톱 빌드 방법, 플랫폼별 준비 사항과 기존 검증 범위는 [실행 및 빌드 안내](docs/building.md)에 정리되어 있습니다.

## 문서

- [실행 및 빌드 안내](docs/building.md): OS별 실행·패키징, SQLCipher 의존성, 업데이트 배포
- [프로젝트 구조](docs/project-structure.md): 폴더별 역할과 파일 안내
- [기존 자료 이관](docs/legacy-import.md): 울산형 상담기록관리 XLSB 가져오기 절차와 제한

## 라이선스

마음나래는 [MIT 라이선스](LICENSE)로 배포됩니다. 포함된 라이브러리와 글꼴에는 각각의 라이선스가 적용되며, [서드파티 라이선스 안내](resources/licenses/README.md)와 앱의 프로그램 정보 화면에서 확인할 수 있습니다.
