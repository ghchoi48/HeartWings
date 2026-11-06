# 릴리스 소스와 수정한 pyxlsb로 빌드하기

이 문서는 마음나래 소스 ZIP을 받은 사용자가 앱을 빌드하고 수정한 pyxlsb를 사용할 수
있도록 안내합니다. 개발자의 계정·서명 키·Git 저장소 접근 권한은 필요하지 않습니다.
동봉된 memory_xlsb.py와 pyxlsb에는 LGPL-3.0-or-later, 앱의 나머지 자체 코드에는
별도 표시가 없는 한 MIT가 적용됩니다. 원저작권·라이선스·변경 고지를 유지하세요.

## 1. 자료와 환경 확인

정식 빌드는 `python scripts/build_desktop.py`로 만듭니다. 완료되면 `dist/release/`에
실행 파일/설치 프로그램, `*-sources.zip`, `*-release.json`이 함께 생성됩니다.
이를 같은 릴리스에 함께 게시하세요. 스크립트는 게시·업로드하지 않습니다.
JSON의 SHA-256으로 실행 파일과 소스 ZIP의 대응을 확인할 수 있습니다.

소스 ZIP을 새 폴더에 풀고 그 폴더에서 명령을 실행합니다. Git 없이 빌드 가능합니다.
`release/build-environment.json`에는 Python 버전, OS/CPU, Python 패키지 버전,
조회 가능한 SQLCipher·SQLite·시스템 패키지 버전과 각 소스 파일 해시가 들어 있습니다.
`release/requirements-rebuild.txt`는 해당 OS/CPU 환경의 정확한 Python 패키지 목록입니다.
다른 OS에 그대로 설치하지 마세요. OS별 별도 빌드와 기록을 사용하세요.
이 파일은 전체 관찰 환경을 기록하므로 정식 빌드는 전용 가상환경에서 수행하세요.

소스 ZIP은 앱 소스·리소스·빌드 도구·회귀 테스트·동봉 라이선스 소스를 포함합니다.
모든 외부 패키지의 오프라인 미러는 아닙니다. 일반 의존성 설치에는 인터넷이 필요합니다.
패키지 인덱스가 제공하지 않는 플랫폼별 wheel/네이티브 의존성은 아래 환경 준비가 필요합니다.

## 2. Python 및 OS 의존성 준비

기록된 Python 버전과 같은 OS·CPU를 준비합니다. Python 실행 파일에 대한 명령은
이하 `python`으로 표기하며, 가상환경 생성 전 macOS/Linux에서는 `python3`일 수 있습니다.

```sh
python -m venv .venv
```

- macOS/Linux: `source .venv/bin/activate`
- Windows PowerShell: `.venv\Scripts\Activate.ps1`

릴리스 ZIP이라면:

```sh
python -m pip install -r release/requirements-rebuild.txt
```

저장소 소스에서 시작한다면:

```sh
python -m pip install -r requirements/build.txt
python -m pip install setuptools
```

재설치 목록에는 pyxlsb를 제외했습니다. 다음 단계에서 로컬 소스를 마지막으로 설치합니다.
저장소 requirements는 공식 기준 pyxlsb도 먼저 설치하지만 다음 단계가 이를 교체합니다.

OS별 추가 조건:

- Windows: x64 Python(Tcl/Tk 포함), Inno Setup 6.3 이상. 가능하면 기록된 Inno Setup
  버전을 사용하세요. `ISCC.exe`를 PATH에 추가하거나 `ISCC_PATH`를 지정합니다.
  WebView2 Runtime이 필요하며 설치 프로그램은 없을 때 다운로드합니다.
- macOS: 동일 CPU의 macOS와 필요 시 Xcode Command Line Tools. SQLCipher wheel이 없으면
  SQLCipher 및 C 컴파일 도구를 준비합니다. 기록된 네이티브 버전을 참고하세요.
- Linux: GTK 3, PyGObject, WebKit2GTK 및 해당 배포판의 개발 패키지와 빌드 도구가 필요합니다.
  최초 환경 구성에는 `python -m pip install 'pywebview[gtk]'`가 필요할 수 있습니다.
- SQLCipher: 대상 Python/OS/CPU용 sqlcipher3 wheel이 없으면 SQLCipher 헤더·라이브러리와
  컴파일러를 준비해야 합니다. Python 버전 기록만으로 네이티브 환경이 재현되지는 않습니다.

시스템 패키지/설치 도구 버전이 자동 수집되지 않았다면 배포자는 그 버전과 설치 방법을
릴리스 설명에 추가하세요. 서명·공증·운영체제 정책은 빌드 의존성과 구분합니다.

## 3. 실제 사용된 pyxlsb 소스 준비 및 수정

```sh
python packaging/prepare_local_pyxlsb.py
```

동봉된 `heartwings-xlsb-sources.zip`의 실제 사용 소스를 `build/pyxlsb-local/`에 풀고
pip 설치용 설정과 GPL/LGPL 고지를 만듭니다. 공식 기준 원본은 별도의 tar.gz에 있습니다.
기존 출력 폴더는 덮어쓰지 않습니다. 다른 위치가 필요하면 `--output build/pyxlsb-other`를 사용합니다.

`build/pyxlsb-local/pyxlsb/`에서 필요한 코드를 수정하세요. 변경 내용·수정 날짜·저작권을
소스와 CHANGES.md에 기록하고 LGPL을 유지합니다. 앱의 어댑터를 수정하려면
`maeumnarae/services/memory_xlsb.py`를 수정합니다. 원본 버전과의 바이트 일치를 강제하지 않습니다.

```sh
python -m pip install --no-deps --no-build-isolation --force-reinstall ./build/pyxlsb-local
python -c "import pyxlsb; print(pyxlsb.__version__, pyxlsb.__file__)"
python packaging/prepare_pyxlsb_sources.py
python -m unittest discover -s tests -v
```

설치 명령의 `--no-deps`는 수정본 설치 중 다른 패키지를 바꾸지 않도록 합니다.
이후 `pip install -r requirements/build.txt`나 공식 pyxlsb 재설치를 실행하면 수정본을
덮어쓸 수 있으므로 실행하지 마세요. 빌드 스크립트 자체는 pip 설치를 수행하지 않습니다.
수정으로 의도적인 동작 변경이 생겼다면 기존 회귀 기대값과 차이를 검토하세요.
테스트 성공을 강제하는 빌드 잠금은 없습니다.

## 4. 수정본 빌드 및 실행

```sh
python scripts/build_desktop.py
```

빌드 전 사용된 라이브러리·파생 소스 ZIP을 새로 생성하고, 앱 소스와 환경을 기록합니다.
빌드 도중 소스나 환경이 바뀌면 대응 자료가 잘못 생성되지 않도록 중단합니다.

개발자의 서명 키를 사용하지 않는 로컬 빌드를 지원합니다. macOS spec은 개인 서명 ID를
지정하지 않으며, Windows Inno Setup 설정에도 인증서 서명 명령을 요구하지 않습니다.
개인 서명·공증이 있는 공식 배포본과 동일한 신뢰 표시는 보장하지 않습니다.

수정본 검증에는 별도 DB를 사용하세요. 운영 DB를 복사하거나 덮어쓸 필요가 없습니다.

- Windows PowerShell: `& .\dist\maeumnarae\maeumnarae.exe --db .\build\modified-test.db`
- macOS: `./dist/마음나래.app/Contents/MacOS/maeumnarae --db ./build/modified-test.db`
- Linux: `./dist/maeumnarae/maeumnarae --db ./build/modified-test.db`

Windows는 설치 프로그램 없이 `dist/maeumnarae` 전체(내부 리소스 포함)로 실행할 수도
있습니다. 설치 프로그램을 실행하면 같은 AppId의 기존 설치에 영향을 줄 수 있으므로
수정본 검증에는 위 폴더 실행을 사용하세요. macOS도 빌드 디렉터리의 앱으로 실행할 수 있습니다.
OS가 실행을 제한하면 해당 OS가 제공하는 앱 실행 승인 절차를 사용하세요.

배포할 때는 `dist/release/`에서 이번 빌드에 해당하는 실행 파일·소스 ZIP·release.json을
함께 제공하세요. 오래된 타깃/버전 파일을 섞지 마세요. 소스 ZIP과 설치 파일을 게시하기
전에 실제 설치본의 XLSB 가져오기와 소스 저장 버튼을 확인해야 합니다.

## 5. 소스 자료만 생성 / 현재 검증 범위

```sh
python scripts/build_desktop.py --sources-only
```

실행 파일을 만들지 않고 현재 환경의 소스 자료를 `dist/source-preview/`에 생성합니다.
정식 릴리스의 소스 ZIP을 덮어쓰지 않습니다. 상태는
`source-only-unverified`이며 실제 배포 실행 파일에 대응한다고 주장하지 않습니다.
정상 빌드 경로는 `paired-build`와 바이너리 해시를 기록하지만, 이것도 GUI·OS별 설치 검증
완료를 의미하지 않습니다. 수동으로 spec만 실행하면 전체 릴리스 자료는 생성되지 않습니다.

이 단계의 자동 검증은 소스 패키징, 자료 누락/민감 파일 제외, 수정본 설치 경로와
파일 대응을 다룹니다. 모든 OS에서 수정본 앱을 빌드·설치·사용하는 최종 검증은 별도입니다.

## 6. 빌드된 실행 파일에서 데이터·고지 검증

실행 파일에 다음 인자를 전달하면 GUI·서버·사용자 DB를 열지 않고 실제 번들 모듈로
합성 XLSB를 읽고 동봉 원본/사용 소스와 라이선스 접근을 검사합니다.

```sh
./dist/마음나래.app/Contents/MacOS/maeumnarae --verify-distribution tests/fixtures/legacy_import/synthetic.xlsb --verification-report build/distribution-check.json
```

Windows/Linux는 앞서 안내한 해당 실행 파일 경로로 바꿉니다.
성공 시 종료 코드 0, 실패 시 1이며 JSON에 결과를 기록합니다.
`frozen: true`, 실제 pyxlsb 버전, 행 번호, 날짜 변환, 소스 해시와 이관 지문을 확인합니다.
기본 합성 자료의 지문은 `tests/fixtures/legacy_import/baseline.json`과 같아야 합니다.
이 검사는 화면 조작·설치 프로그램·서명/공증 확인을 대신하지 않습니다.

릴리스 해시와 frozen 실행 결과를 함께 대조하려면:

```sh
python packaging/check_release.py dist/release/maeumnarae-1.1.0-darwin-arm64-release.json --frozen-report build/distribution-check.json
```

파일명은 실제 버전·OS·CPU에 맞게 바꿉니다. 이 명령은 소스/바이너리 해시,
환경에 기록된 pyxlsb 버전, 실제 실행 버전, 기존 이관 지문 및 실행 파일의 동봉 소스와
릴리스 소스의 일치를 확인합니다. `gui: not_checked`는 별도 화면 확인이 필요하다는 뜻입니다.

## 로컬 AI 엔진 준비와 검증

지원 플랫폼에서 PyInstaller 실행 전에 다음 명령으로 고정된 공식 엔진을 준비합니다.

```bash
python scripts/prepare_ai_engine.py
python scripts/prepare_ai_engine.py --verify
python scripts/build_desktop.py
```

`resources/ai/engines.json`은 llama.cpp 버전과 Windows x64 CPU/macOS arm64 아카이브의
SHA-256을 고정합니다. 준비 스크립트는 검증 후 `resources/ai/runtime/<플랫폼>/`에
실행 파일과 동적 라이브러리를 설치합니다. 이 생성 파일들은 Git 및 배포 소스 ZIP에서
제외하지만 PyInstaller 앱에는 포함합니다. 지원 플랫폼의 파일 누락·변조는 빌드를
실패시킵니다. Linux·Intel Mac 빌드는 AI 엔진 없이 기존 기능만 제공합니다.

모델 가중치는 설치 파일에 포함하지 않습니다. `resources/ai/models.json`에 공식
revision·크기·SHA-256·라이선스·실행 프로필을 함께 고정합니다. 모델/엔진 업데이트 시
두 지원 플랫폼에서 생성·취소·DB 잠금·앱 종료·오프라인 실행을 다시 검증하세요.
macOS 배포 서명·공증에는 동봉된 엔진과 dylib도 포함해야 합니다.

```bash
python -m unittest discover -s tests -p 'test_ai*.py' -v
```

자동화 테스트는 실제 모델을 내려받지 않습니다. 실기기 검증은 설정 → AI에서 EXAONE
다운로드 → 선택 → 한국어 테스트 생성 → 중지/Off → 재시작으로 수행합니다.
8GB 장치의 메모리·응답속도 및 Windows CPU 검증은 해당 장치에서 별도로 확인해야 합니다.
추론 엔진은 임시 인증키가 적용된 루프백으로만 실행되며 Python 서버가 호출합니다.
감시 프로세스는 부모 파이프가 닫히면 엔진을 종료합니다. 엔진 stdout/stderr와 입력·출력은
로그로 저장하지 않습니다.
