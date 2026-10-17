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
python -m pip install -r requirements-desktop.txt
python main.py
# 같은 네이티브 모드, DB를 별도로 지정:
python main.py --native --db ./data/maeumnarae.db
# 선택적으로 브라우저 모드:
python main.py --browser --port 8080
```

네이티브는 빈 포트를 선택하고 127.0.0.1에만 연결합니다. 기본 DB는 사용자 데이터 폴더에 저장하므로
앱 업데이트로 번들을 교체해도 기록이 유지됩니다. 종료 전 입력 내용을 저장하세요.
오류 로그는 DB 폴더의 `logs/maeumnarae.log`에서 확인할 수 있습니다.

## OS별 빌드

```bash
python -m pip install -r requirements-build.txt
python scripts/build_desktop.py
```

- macOS: Cocoa/WebKit 백엔드와 PyObjC를 사용합니다. `dist/마음나래.app` 및 ZIP 생성.
- Windows: Microsoft Edge WebView2 Runtime이 필요합니다. 대상 환경에 런타임을 설치하고 같은 아키텍처로 빌드합니다. 결과는 `dist/maeumnarae/maeumnarae.exe`이며 폴더 전체를 배포합니다.
- Linux: GTK 백엔드를 사용하므로 PyGObject, GTK 3, WebKit2GTK 및 배포판별 개발 패키지가 필요합니다. 빌드 환경에 `pywebview[gtk]`를 설치하세요. 결과는 `dist/maeumnarae/maeumnarae`이며 폴더 전체를 배포합니다. 대상 glibc/GUI 라이브러리 호환성은 별도 검증이 필요합니다.

Windows/Linux의 위 절차는 빌드 가이드이며 이번 환경에서는 실행하지 않았습니다.
`maeumnarae.spec`은 NiceGUI 정적 파일, pywebview 리소스 및 플랫폼별 백엔드를 수집합니다.
`main.py`는 frozen 자식 프로세스가 UI를 중복 실행하지 않도록 NiceGUI import 전에 `freeze_support()`를 호출합니다.

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
- 빌드 로그: `artifacts/build-desktop.log`. 네이티브 로그: `artifacts/packaged-native.log`.
- `Iphlpapi` 누락 빌드 경고는 Windows용 의존성으로 macOS 실행에는 사용되지 않았습니다.

새 OS/장치 배포 전에는 새 DB 생성, 재열기, 잘못된 키 거부, 학생/상담 저장,
캘린더/통계, 보고서 저장, 창 종료를 실제 대상 환경에서 확인하세요.
앱 서명·공증이나 OS 검증이 완료된 것으로 간주하지 마세요.
