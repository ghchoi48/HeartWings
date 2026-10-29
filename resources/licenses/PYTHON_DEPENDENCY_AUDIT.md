# Python 전이 의존성 고지 점검

확인일: 2026-10-29. 대상: macOS arm64 검증용 `maeumnarae-macos.zip`.
이 산출물은 수정 pyxlsb를 사용한 검증용 빌드이며 정식 배포본이 아닙니다.

## 포함 여부와 버전 근거

실행 파일의 PyInstaller `PYZ.pyz` 모듈 목록과 앱의 `.so`·`.py` 파일을
빌드 환경의 Python distribution 메타데이터에 연결했습니다. 환경에 설치되어 있다는
이유만으로 포함 판정을 하지 않았습니다. 버전은 대응 릴리스 JSON과 대조했습니다.
원본 실행 파일은 실행하거나 수정하지 않고 압축 파일로 읽었습니다.

- 식별된 Python 배포 패키지: **69개**
- 기존 고지에 추가한 패키지: **54개**
- 추가 보존한 원문 파일: **89개** (LICENSE, NOTICE, AUTHORS 및 필요한 소스 내 고지)
- 각 모듈·파일의 포함 근거와 실행 파일 ZIP 해시: [PYTHON_BUNDLE_INVENTORY.json](PYTHON_BUNDLE_INVENTORY.json)
- 수록 경로, 출처, 개별 원문 및 화면 표시용 합본 해시: [manifest.json](manifest.json)의 `license_files`와 `license_sha256`

원본 파일은 `python/<패키지>/`에 바이트 단위로 보존했습니다.
`libraries/<패키지>.txt`는 원본 경로 구분선을 추가한 화면 표시용 합본입니다.
NOTICE는 aiofiles, propcache, yarl 및 setuptools의 2개 파일을 함께 수록했습니다.
패키지에서 제공하는 복수 라이선스와 하위 구성요소의 원문도 함께 보존했습니다.

## 별도 확인한 사항

- PyObjC core, Security, UniformTypeIdentifiers의 설치 배포본에는 라이선스 원문이 없어
  정확히 12.2.2인 공식 소스 배포본의 License.txt를 추출했습니다. 원본 URL과 소스 해시를 기록했습니다.
- proxy_tools 0.1.0의 배포 메타데이터는 MIT이지만 코드 헤더와 공식 LICENSE.txt는 BSD입니다.
  공식 저장소 커밋 `db43f1e35d4f90a65c5a4d56d9e9af88212ec6e6`의 코드가 설치된
  `proxy_tools/__init__.py`와 동일함을 확인하고 해당 BSD 원문과 코드의 저작권 표시를 보존했습니다.
- bidict 0.24.1은 MPL-2.0, orjson 3.12.0은 `MPL-2.0 AND (Apache-2.0 OR MIT)`입니다.
  공식 원본 소스 배포본을 `sources/`에 동봉했고 프로그램 정보의 기존 소스 저장 기능에 연결했습니다.
  이는 공식 원본 제공이며 수정본의 대응 소스 검증이나 네이티브 내부 구성요소의 전수 조사 완료를 뜻하지 않습니다.
- pytest를 제외하는 spec 설정이 있어도 실제 PYZ에는 `_pytest`, `_pytest._version`,
  `_pytest.outcomes`가 포함되어 있으므로 pytest 고지도 수록했습니다.
- Docutils의 COPYING이 참조하는 복수 원문과 smartquotes·수학 변환 코드의 고지도 보존했습니다.
  소스 배포본에 대한 GPL 관련 설명을 앱 전체 라이선스로 해석하지 않습니다.
- setuptools의 vendored 패키지 고지는 배포본에 있는 원문을 함께 수록했습니다.

## 재검증

빌드에 사용한 Python 환경에서 다음 명령을 실행합니다. PyInstaller가 필요합니다.
현재 검증용 pyxlsb의 로컬 버전 접미사는 기준 원본 1.0.10과 구분하여 기록합니다.

```sh
python packaging/audit_python_notices.py \
  --archive dist/validation-macos/maeumnarae-macos.zip \
  --release dist/validation-macos/maeumnarae-1.1.0-darwin-arm64-release.json
python -m pytest -q tests/test_python_notices.py tests/test_release_sources.py
```

69개 고지 대응 검사 및 7개 테스트가 통과했습니다. 테스트는 누락, 잘못된 버전,
변조된 원문을 거부하는지와 프로그램 정보의 원문 읽기·오프라인 소스 접근을 검사합니다.
GUI 버튼의 실제 클릭이나 재빌드는 이번 단계에서 수행하지 않았습니다.

새 macOS 빌드는 해당 ZIP과 대응 릴리스 JSON을 지정하고 `--output <경로>`로 새 목록을 기록할 수 있습니다.
이 검사는 현재 환경의 모듈→패키지 매핑을 사용하므로 반드시 해당 빌드 환경에서 수행합니다.
새 패키지가 발견되면 원문을 수집하고 manifest를 갱신한 후 다시 검사합니다.
이 도구는 macOS 앱 ZIP용이며 Windows·Linux·CLI 배포물에는 별도 포함 목록 검사가 필요합니다.

## 범위와 다음 단계

이번 변경은 저장소의 Python 패키지 고지를 보완했습니다. 기존 검증용 ZIP·앱의 고지는
갱신되지 않았으므로 새 실행 파일과 대응 소스 ZIP을 빌드해야 반영됩니다.
두 spec과 릴리스 소스 수집기는 licenses 폴더 전체를 포함합니다.

Python 런타임, OpenSSL·libuv 등 네이티브 라이브러리, Rust 확장 내부 구성요소,
NiceGUI 웹 자산과 폰트는 다음 항목의 점검 대상입니다. 이 목록은 전체 구성요소 SBOM이나
정식 배포 승인 기록이 아닙니다. 다른 OS 또는 다른 버전으로 빌드하면 다시 조사해야 합니다.

## 추가한 고지

| 패키지 | 버전 | 수록 라이선스 표시 |
|---|---|---|
| aiofiles | 25.1.0 | Apache-2.0 |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 |
| aiohttp | 3.14.3 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache-2.0 |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| bidict | 0.24.1 | MPL-2.0 |
| bottle | 0.13.4 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| docutils | 0.23 | Public domain and BSD; see COPYING exceptions |
| frozenlist | 1.8.0 | Apache-2.0 |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httptools | 0.8.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.19 | BSD-3-Clause |
| ifaddr | 0.2.0 | MIT |
| itsdangerous | 2.2.0 | BSD-3-Clause |
| Jinja2 | 3.1.6 | BSD-3-Clause |
| MarkupSafe | 3.0.3 | BSD-3-Clause |
| multidict | 6.9.1 | Apache-2.0 |
| orjson | 3.12.0 | MPL-2.0 AND (Apache-2.0 OR MIT) |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| propcache | 0.5.2 | Apache-2.0 |
| proxy_tools | 0.1.0 | BSD-2-Clause (source notice; package metadata says MIT) |
| pydantic_core | 2.46.5 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| pyobjc-core | 12.2.2 | MIT |
| pyobjc-framework-Cocoa | 12.2.2 | MIT |
| pyobjc-framework-Quartz | 12.2.2 | MIT |
| pyobjc-framework-Security | 12.2.2 | MIT |
| pyobjc-framework-UniformTypeIdentifiers | 12.2.2 | MIT |
| pyobjc-framework-WebKit | 12.2.2 | MIT |
| pytest | 9.1.1 | MIT |
| python-dateutil | 2.9.0.post0 | Apache-2.0 OR BSD-3-Clause |
| python-dotenv | 1.2.3 | BSD-3-Clause |
| python-engineio | 4.14.0 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| python-socketio | 5.17.0 | MIT |
| PyYAML | 6.0.3 | MIT |
| setuptools | 84.0.0 | MIT |
| six | 1.17.0 | MIT |
| tinycss2 | 1.5.1 | BSD-3-Clause |
| typing_extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| uvicorn | 0.53.0 | BSD-3-Clause |
| uvloop | 0.22.1 | MIT AND Apache-2.0 (see bundled texts) |
| watchfiles | 1.2.0 | MIT |
| webencodings | 0.6.1 | BSD-3-Clause |
| websockets | 17.1 | BSD-3-Clause |
| wsproto | 1.3.2 | MIT |
| yarl | 1.24.5 | Apache-2.0 |
