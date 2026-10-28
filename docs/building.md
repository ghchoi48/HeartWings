# 마음나래 데스크톱 실행 및 빌드

## 바로 실행

현재 제공된 `dist/마음나래.app` 또는 `dist/maeumnarae-macos.zip`은 **macOS Apple Silicon(arm64)** 용입니다.
ZIP을 풀고 앱을 열면 별도 Python 설치 없이 네이티브 창이 열립니다.
최초 화면에서 사용할 DB 비밀번호를 직접 설정하세요. 실제 기록과 비밀번호는 배포 파일에 포함하지 않았습니다.
기본 DB 위치는 `~/Library/Application Support/maeumnarae/data/maeumnarae.db`입니다.

현재 산출물은 로컬 테스트용 ad-hoc 서명이며 Apple Developer ID 서명·공증은 하지 않았습니다.
다른 Mac 배포 시 서명·공증을 진행하고 깨끗한 대상 장치에서 다시 검증하세요.
Intel Mac, Windows, Linux 실행 파일은 각 대상 OS/CPU에서 별도로 빌드해야 합니다.

## 소스 실행

가상환경을 만든 뒤 다음을 실행합니다.

```bash
python -m pip install -r requirements/desktop.txt
python main.py
# 같은 네이티브 모드, DB를 별도로 지정:
python main.py --native --db ./data/maeumnarae.db
# 선택적으로 브라우저 모드:
python main.py --browser --port 8080
```

네이티브는 빈 포트를 선택하고 127.0.0.1에만 연결합니다. 기본 DB는 사용자 데이터 폴더에 저장하므로
앱 업데이트로 번들을 교체해도 기록이 유지됩니다. 종료 전 입력 내용을 저장하세요.
배포 앱의 오류 로그는 실행 파일 옆 `logs/maeumnarae.log`에서 확인할 수 있습니다.
콘솔 없는 실행에서는 초기 출력과 예외도 프로세스별 `startup-날짜-시간-PID.log`에 기록합니다.
초기 로그도 실행 파일 옆 `logs` 폴더에 저장하며, 현재 작업 폴더나 `--db` 지정과 무관합니다.
Windows에서 해당 위치에 쓰지 못하면 `%LOCALAPPDATA%\maeumnarae\data\logs`,
그다음 `%TEMP%\maeumnarae\logs`를 사용합니다. 소스 실행의 운영 로그는 DB 폴더 아래에 저장합니다.
초기 로그는 자동 회전하지 않으므로 진단 후 불필요한 파일은 삭제할 수 있습니다.

## DB 스키마 기준

최초 배포 기준 스키마 버전은 **1**입니다. 새 DB는 현재의 테이블·인덱스·트리거를 한 트랜잭션으로 생성하며, 개발 중 사용했던 버전 2~38의 단계별 마이그레이션은 제공하지 않습니다. 버전 1 DB를 다시 열 때는 기존 데이터와 학교 설정을 유지합니다.

참여 학생 출석 기능이 추가되기 전의 버전 1 DB에는 집단 상담 일지의 출석 저장 열을 자동으로 추가합니다. 기존 일지 내용은 유지되며 출석·참여 태도는 빈 기록으로 시작합니다.

Wee센터 선택을 지원하지 않는 버전 1 DB는 학교급 제약 조건을 자동으로 확장합니다. 기존 학교 정보와 작성자 정보는 유지합니다.

기존 개발용 DB는 자동으로 삭제하거나 변환하지 않습니다. 새 구조로 테스트하려면 별도 경로를 지정하세요.

```bash
python main.py --db ./data/maeumnarae-v1.db
```

백업 복원도 버전 1 DB를 대상으로 합니다.

## OS별 빌드

### GitHub Releases 업데이트 알림

배포 전 `maeumnarae/core/program_info.py`의 `PROGRAM_VERSION`을 배포할 버전으로 변경하고 빌드합니다.
GitHub `ghchoi48/HeartWings` 저장소에 같은 버전 태그(예: `v1.0.1`)로 정식 Release를
게시하고 최신 릴리스로 지정하세요. 태그는 `v1.2.3` 또는 `1.2.3` 형식을 사용합니다.
Release 본문에 변경사항을 작성하고 OS별 배포 파일을 첨부합니다.

앱은 실행 시 공개 GitHub Releases API로 한 번 확인합니다. 현재 버전보다 높은 정식
버전이 있으면 변경사항과 함께 **새 버전 알림**을 표시합니다. **취소**는 알림을 닫고,
**다운로드 페이지 이동**은 기본 브라우저에서 해당 릴리스 페이지를 엽니다.
초안·사전 릴리스는 제외하며, 오프라인·시간 초과·API 제한·릴리스 없음은 조용히 건너뜁니다.
DB 잠금 해제나 화면 이동으로는 다시 확인하지 않으며, 다음 실행 때 다시 확인합니다.

### 빌드 명령

```bash
python -m pip install -r requirements/build.txt
python scripts/build_desktop.py
```

- macOS: Cocoa/WebKit 백엔드와 PyObjC를 사용합니다. `dist/마음나래.app` 및 ZIP 생성.
- Windows: x64 Windows의 x64 Python과 Inno Setup 6.3 이상이 필요합니다. `dist/maeumnarae/maeumnarae.exe` 및 `dist/installer/maeumnarae-<버전>-windows-x64-setup.exe`를 생성합니다. 설치 파일 대신 폴더로 배포할 때는 `dist/maeumnarae` 전체를 전달하고 WebView2 Runtime을 별도로 준비합니다.
- Linux: GTK 백엔드를 사용하므로 PyGObject, GTK 3, WebKit2GTK 및 배포판별 개발 패키지가 필요합니다. 빌드 환경에 `pywebview[gtk]`를 설치하세요. 실행 파일은 `dist/maeumnarae/maeumnarae`이며, `dist/maeumnarae` 폴더 전체를 배포합니다. 대상 glibc/GUI 라이브러리 호환성은 별도 검증이 필요합니다.

Windows/Linux의 위 절차는 빌드 가이드이며 이번 환경에서는 실행하지 않았습니다.
`packaging/maeumnarae.spec`은 NiceGUI 정적 파일, pywebview 리소스 및 플랫폼별 백엔드를 수집합니다.
폴더 배포 모드(`--onedir`에 해당)는 spec의 `EXE(exclude_binaries=True)`와 `COLLECT`에 설정되어 있으므로 빌드 명령에 별도 옵션을 추가하지 않습니다.
macOS 앱 번들도 수집된 폴더를 기반으로 생성합니다. Windows/Linux에서는 실행 파일과 함께 `_internal` 폴더를 포함한 전체 배포 폴더를 유지하세요.
`main.py`는 frozen 자식 프로세스가 UI를 중복 실행하지 않도록 NiceGUI import 전에 `freeze_support()`를 호출합니다.

### Windows 설치 파일 빌드

Windows 배포 앱은 실행 직후 로고 스플래시를 표시하고 실제 네이티브 창의 `shown`
이벤트에서 닫습니다. 시작 실패·시간 초과·프로세스 종료 시에도 정리합니다.
[PyInstaller Splash](https://pyinstaller.org/en/stable/spec-files.html#splash-screen)를
사용하므로 Windows 빌드용 Python에는 Tcl/Tk가 포함되어 있어야 합니다
(python.org 설치 프로그램의 Tcl/Tk 옵션). 소스 실행과 macOS/Linux 빌드에는 표시하지 않습니다.
`--browser`/`--help` 실행에서는 Python 진입 시 바로 닫습니다.
이미지는 `resources/icons/splash.png`이며, 로고나 문구를 수정한 뒤
`python scripts/build_splash.py`로 재생성하고 앱을 다시 빌드하세요.
Windows에서 배포 전 실행 직후 표시, 메인 창 표시 시 사라짐, 시작 실패 시 정리를 확인하세요.

1. x64 Windows에 x64 Python과 [Inno Setup 6.3 이상](https://jrsoftware.org/isdl.php)을 설치합니다.
2. 가상환경에서 `python -m pip install -r requirements/build.txt`를 실행합니다.
3. `python scripts/build_desktop.py`를 실행하면 onedir 빌드 후 Inno Setup 컴파일이 이어집니다.

컴파일러는 `ISCC_PATH` 환경변수, PATH의 `ISCC.exe`, Program Files (x86), Program Files,
현재 사용자의 `AppData/Local/Programs` 아래 `Inno Setup 6/ISCC.exe` 순서로 찾습니다.
다른 위치에 설치했다면 PowerShell에서 다음처럼 지정하세요. 환경변수 값에는 따옴표 자체를 포함하지 않습니다.

```powershell
$env:ISCC_PATH = 'C:\Tools\Inno Setup 6\ISCC.exe'
python scripts/build_desktop.py
```

컴파일러 누락 또는 지원하지 않는 Python 아키텍처는 PyInstaller 실행 전에 오류로 종료합니다.
PyInstaller나 Inno Setup이 실패해도 빌드 명령은 실패 종료합니다.
이름과 버전은 `maeumnarae/core/program_info.py`에서 읽으며, 버전은 숫자 3~4개를 점으로 구분합니다.
한국어 번역은 `packaging/languages`에 포함되어 있습니다. 코드 서명과 자동 배포는 수행하지 않습니다.

설치 파일은 관리자 권한 없이 기본적으로 `%LOCALAPPDATA%\Programs\maeumnarae`에 설치합니다.
시작 메뉴 바로가기를 생성하며 바탕 화면 바로가기는 기본 선택 상태로 제공하므로 해제할 수 있습니다.
고정 AppId로 기존 설치를 업데이트하며 실행 중인 앱은 저장 후 종료해야 합니다.
설치 완료 화면에서 앱 실행을 선택할 수 있습니다.

WebView2가 없으면 [Microsoft의 배포 지침](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution)에 따라
공식 Evergreen Bootstrapper를 다운로드하여 설치합니다. 이 경우 인터넷 연결이 필요합니다.
다운로드·실행·설치 확인 실패 시 앱 파일 설치를 진행하지 않고 오류를 표시합니다.
이미 WebView2가 있으면 다운로드하지 않으며 제거 시 공유 런타임도 유지합니다.

### Windows 제거와 데이터 보존

제거할 때는 먼저 앱을 종료하세요. **사용자 DB 및 설정 파일도 삭제**는 기본 선택 해제 상태입니다.
선택하면 실제 경로를 보여주고 영구 삭제를 별도로 확인합니다. 확인에서 아니요를 선택하면 제거를 취소합니다.
앱 제거 후 현재 사용자의 `%LOCALAPPDATA%\maeumnarae\data` 아래 다음 파일만 삭제합니다.

- `maeumnarae.db`
- `maeumnarae.db-wal`, `maeumnarae.db-shm`, `maeumnarae.db-journal` (SQLite 보조 파일)
- `display-settings.json` (화면 설정 등 앱 설정)

데이터 폴더 자체, 로그, 별도 백업·내보낸 파일, `--db`로 지정한 다른 경로의 DB와 설정은 삭제하지 않습니다.
기본 경로에 있는 파일은 위 목록에 따라 처리됩니다. 삭제 실패 시 실패 경로와 시스템 오류를 표시하며,
DB 삭제에 실패하면 복구용 보조 파일을 보존하기 위해 이후 삭제도 중단합니다.
무인 제거(`/SILENT`, `/VERYSILENT`)는 데이터를 보존합니다. 업데이트는 제거 프로그램을 호출하지 않으므로
데이터 삭제 옵션도 표시하거나 실행하지 않습니다.

### Windows 검증 상태와 배포 전 확인

현재 macOS에서는 빌드 도구 탐색, 메타데이터 전달, 플랫폼 분기, 실패 전파를 모의 실행 테스트로 검증했습니다.
Inno Setup 실제 컴파일과 Windows 설치·실행은 **미검증**입니다. 배포 전 x64 Windows에서 확인하세요.

- 실제 설치 파일 생성, 일반 사용자 설치·실행, 한글 및 공백이 포함된 경로.
- 바탕 화면 바로가기 기본 선택과 해제, 시작 메뉴 바로가기, 완료 후 앱 실행.
- WebView2가 있는 환경, 없는 환경의 온라인 설치, 네트워크 실패 시 앱 설치 중단.
- 기존 버전 위 업데이트, 실행 중 앱 종료 요청, 기존 DB와 설정 유지.
- 기본 제거의 데이터 보존, 삭제 선택 후 취소, 최종 확인 후 지정 파일만 삭제.
- 외부 DB·설정, 별도 백업·내보낸 파일 보존, 무인 제거의 데이터 보존.
- 잠긴 파일 등 삭제 실패 시 경로와 오류 표시, 데이터가 남았다는 안내.

## 일지 PDF 출력

현재 일지 PDF 출력 UI는 숨겨져 있습니다. 출력 코드는 유지하며 아래는 기능을 다시 표시했을 때의 사용법입니다.

각 일지 목록에서 여러 건을 선택해 PDF로 출력하거나 저장된 일지의 `PDF 출력` 버튼을 사용합니다.
수정 중인 내용은 먼저 저장하세요. 설정의 **학년도별 일지 PDF**에서는 해당 학년도 3월 1일부터
다음 해 2월 말일까지의 일지를 한 파일로 내려받습니다. 기본 상태는 완료이며 예약·취소를 추가할 수 있습니다.
심리검사·교육/행사는 상태가 없어 항상 포함됩니다.

PDF는 개인상담·집단상담·특별교육·자문·심리검사·교육/행사 순서이며, 학생·집단·교사별로 묶습니다.
각 묶음 안에서는 날짜순입니다. 비밀 메모·별도 사례 보고서·연락처·가족 정보·첨부파일은 제외합니다.
이름 가리기는 대상자·참여자 필드와 책갈피에 적용하며, 본문에 직접 적은 이름은 자동으로 가리지 않습니다.
PDF 파일을 열어 인쇄하세요. 생성에는 인터넷이나 별도 브라우저 설치가 필요하지 않습니다.

PDF 기본 서체는 리디바탕입니다. ReportLab에서 사용할 수 있도록 공식 OTF를 TTF로 변환하고
이름을 변경한 `resources/fonts/RIDIBatang/HeartWingsRidiBatang-Regular.ttf`를 배포에 포함합니다.
제목·굵은 강조는 기존 Noto Sans KR 기반 `JournalSans-Bold.ttf`를 사용합니다.
변환 방법과 출처는 `resources/fonts/RIDIBatang/README.md`, 라이선스는 `resources/licenses/fonts/ridibatang.txt`에 있습니다.
폰트 생성 도구 fontTools와 PDF 검사용 pypdf/렌더러는 사용자 앱 실행에 필요하지 않습니다.

## SQLCipher 네이티브 의존성

`sqlcipher3` 확장 모듈과 동적 라이브러리를 spec에서 수집합니다. 플랫폼/Python/CPU에 맞는 wheel이
없으면 SQLCipher와 컴파일러를 준비하여 소스 빌드해야 합니다. 자체 공유 라이브러리 빌드는 전이 의존성
(OpenSSL, DLL/dylib/so 등)도 포함하고 필요 시 spec의 `binaries`에 추가하세요.
평문 sqlite로 대체하거나 `sqlcipher3-binary`/`pysqlcipher3`를 혼합 설치하지 않습니다.
드라이버가 없거나 암호화 기능을 사용할 수 없으면 앱은 명시적으로 실패합니다.

## 실제 검증 결과 (2026-10-15)

환경: macOS arm64, Python 3.14, NiceGUI 3.18.0, pywebview 6.2.1,
PyInstaller 6.22.3, sqlcipher3 0.6.4, PyObjC 12.2.2.

- 자동 테스트: 25개 및 하위 사례 7개 통과. SQLCipher 암호화/잘못된 키, CRUD, 통계 경계, 잠금 후 접근 차단 포함.
- 소스 네이티브 창: 테스트용 암호화 DB 로그인, 가상 학생 추가 확인.
- 패키징된 `.app`: 기존 가상 학생 조회, 수정 저장 및 별도 DB 재열기로 보존 확인.
- 명령행 옵션 없이 앱 번들을 직접 열어 기본 네이티브 로그인 화면 표시 확인.
- DB 잠금 → 로그인 화면 → 다시 열기 확인.
- 통계 CSV: macOS 저장 대화상자에서 실제 파일 저장, UTF-8 BOM과 CSV 10행 확인.
- 종료 확인 → 창 닫기 → 프로세스 종료 코드 0 및 로컬 포트 해제 확인.
- `codesign --verify --deep --strict` 통과. Developer ID 서명·공증과는 별개입니다.
- 빌드 로그: `artifacts/logs/build-desktop.log`. 네이티브 로그: `artifacts/logs/packaged-native.log`.
- `Iphlpapi` 누락 빌드 경고는 Windows용 의존성으로 macOS 실행에는 사용되지 않았습니다.

새 OS/장치 배포 전에는 새 DB 생성, 재열기, 잘못된 키 거부, 학생/상담 저장,
캘린더/통계, 보고서 저장, 창 종료를 실제 대상 환경에서 확인하세요.
앱 서명·공증이나 OS 검증이 완료된 것으로 간주하지 마세요.
