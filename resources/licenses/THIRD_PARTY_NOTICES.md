# 마음나래 서드파티 고지 및 소스 안내

마음나래 자체 코드는 별도 표시된 부분을 제외하고 MIT 라이선스입니다.
`maeumnarae/services/memory_xlsb.py`에는 LGPL-3.0-or-later가 적용됩니다. 포함된 서드파티 구성요소의 저작권은
각 권리자에게 있으며 각자의 라이선스가 적용됩니다. 원문 목록은
[manifest.json](manifest.json), 라이브러리 원문은 `libraries/`, 폰트 원문은 `fonts/`에 있습니다.
프로그램의 설정 → 프로그램 정보에서도 등록된 고지를 확인할 수 있습니다.

## 이 자료의 범위

이 문서는 저장소의 고지 자료입니다. 실제 설치본 전체에 대한 라이선스 점검 완료를
의미하지 않습니다. requirements에는 버전 범위와 고정 버전이 섞여 있고 OS마다 배포 구성요소가 다를 수 있습니다.
이번에 대조한 버전과 수록 원문은 다음과 같습니다. 현재 설치 환경 및 macOS arm64
검증용 빌드 기록을 기준으로 하며, 정식 릴리스 전체의 검증 완료를 의미하지 않습니다.

| 구성요소 | 고지 대상 버전 | 라이선스 및 범위 |
|---|---|---|
| Pydantic | 2.13.5 | MIT |
| Pillow | 12.3.0 | MIT-CMU; 설치 배포본 LICENSE의 부속 라이브러리 고지도 포함 |
| SQLCipher Community Edition | 4.19.0 | BSD-3-Clause; sqlcipher3 바인딩 및 연결 암호화 라이브러리와 별개 |
| FastAPI | 0.141.1 | MIT |
| Starlette | 1.6.0 | BSD-3-Clause |
| PyInstaller | 6.22.3 (참고 원문) | GPL-2.0-or-later 및 Bootloader 예외; 런타임 훅·추가 런타임 모듈은 Apache-2.0 |

원문은 저작권 표시를 포함해 그대로 보관했고 출처와 SHA-256은 manifest에 기록했습니다.
[버전 대조 기록](VERSION_AUDIT.md)에 추출 경로와 검증 범위를 기록했습니다.
의존성 설치 버전이나 기존 검증용 실행 파일을 변경한 것은 아닙니다.

## Python 전이 의존성

macOS arm64 검증용 실행 파일에서 식별한 Python 배포 패키지 69개에 대응하는 고지를
등록했습니다. 새로 추가한 54개 패키지의 LICENSE·NOTICE 등 원문은 `python/`,
화면 표시용 합본은 `libraries/`에 있습니다.
[포함 근거·수집 경로·재검증 방법](PYTHON_DEPENDENCY_AUDIT.md)을 참고하세요.

bidict 0.24.1 및 orjson 3.12.0의 MPL 대상 코드에 대응하는 공식 원본 소스도
`sources/`에 동봉합니다. 프로그램 정보의 각 항목에서 인터넷 없이 저장할 수 있습니다.
정확한 원본 URL과 해시는 manifest에 기록했습니다. 수정 배포 시에는 실제 수정한
대상 소스를 함께 제공해야 하며, 공식 원본만으로 수정본의 소스 제공을 대신하지 않습니다.

## pyxlsb — LGPL-3.0-or-later

- 공식 배포 기준 및 고지 버전: 1.0.10 (`requirements/base.txt` 고정)
- [공식 원본 소스](https://files.pythonhosted.org/packages/3f/13/eebaeb7a40b062d1c6f7f91d09e73d30a69e33e4baa7cbe4b7658548b1cd/pyxlsb-1.0.10.tar.gz)
- 소스 SHA-256: `8062d1ea8626d3f1980e8b1cfe91a4483747449242ecb61013bc2df85435f685`
- 원문: [GPL 및 LGPL](libraries/pyxlsb.txt), [COPYING](pyxlsb/COPYING), [COPYING.LESSER](pyxlsb/COPYING.LESSER)

- [동봉된 기준 원본](sources/pyxlsb-1.0.10.tar.gz): 공식 sdist를 수정 없이 보관합니다.
- [사용된 라이브러리·파생 소스](sources/heartwings-xlsb-sources.zip): 현재 빌드 환경의
  pyxlsb 소스, 앱의 memory_xlsb.py 및 xlsb_reader.py, 저작권·라이선스·출처 기록입니다.

설정 → 프로그램 정보 → 라이브러리 → pyxlsb에서 두 소스를 인터넷 없이 저장할 수 있습니다.
CLI 번들에서도 내부 리소스 디렉터리의 `resources/licenses/sources/`에서 찾을 수 있습니다.
pyxlsb 및 memory_xlsb.py는 LGPL-3.0-or-later, xlsb_reader.py는 MIT로 제공합니다.

`python packaging/prepare_pyxlsb_sources.py`는 공식 원본 해시·GPL/LGPL 원문을 검증하고
현재 설치된 라이브러리 및 앱 파일을 ZIP으로 묶습니다. 두 PyInstaller spec에서도
자동 실행하므로 파생 구현을 수정하면 배포용 소스 사본이 갱신됩니다.
원본과 다른 pyxlsb도 수록하며, ZIP의 CHANGES.md에 변경 관찰일·차이를 기록합니다.
CONTENTS.json에는 실제 설치 모듈 버전과 파일별 해시를 기록합니다.
`--check`는 현재 코드 및 생성일 기준으로 ZIP이 최신인지 검사하며 배포를 강제하지 않습니다.
수정본 배포자는 자신의 변경 설명·날짜·저작권을 소스에도 유지해야 합니다.

기준 원본의 버전 표시와 실제 사용한 소스 묶음의 버전은 다를 수 있습니다.
수정 배포 시 manifest의 고지 버전·설명도 갱신하세요.
위 원본 링크만으로 수정 소스 제공을 대신하지 않습니다.
실행 파일 배포 시 실제 사용한 라이브러리 소스·수정 내역과, 수정된 라이브러리로
앱을 재결합할 수 있는 앱 소스·빌드 자료 또는 적합한 교체 방식을 제공해야 합니다.
PyInstaller 번들에 포함했다는 사실만으로 교체 가능성을 보장하지 않습니다.
이 저장소의 `maeumnarae/services/memory_xlsb.py`는 원본 Workbook 구현에서 파생된
LGPL-3.0-or-later 파일이며 프로젝트 MIT 적용에서 제외됩니다.
[출처·변경 및 기준 동작 기록](pyxlsb/PROVENANCE.md)에 비교 결과를 기록했습니다.
LGPL이 허용하는 수정 및 수정 사항 디버깅을 위한 역공학을 추가 이용약관으로 제한하지 않습니다.

전체 앱 소스·리소스·환경 기록은 `scripts/build_desktop.py`가 만든 릴리스 소스 ZIP으로 제공합니다.
수정본 준비·설치·재빌드 절차는 저장소 및 소스 ZIP의 `BUILDING.md`에 있습니다.
실제 배포 시 실행 파일과 대응 소스 ZIP을 함께 게시해야 하며, 자동 게시하지 않습니다.
현재 이 문서는 특정 릴리스의 게시·설치 검증 완료를 보증하지 않습니다.
[LGPL 제4조](https://www.gnu.org/licenses/lgpl-3.0.html)에 맞는 배포 경로를 릴리스 전에 확인합니다.

## certifi — MPL-2.0

- 고지 버전: 2026.7.22
- [공식 원본 소스](https://files.pythonhosted.org/packages/a3/c2/24167ea9858356b47a87a50d39908bfdb72ceeefe0041586e704e5376b3a/certifi-2026.7.22.tar.gz)
- 소스 SHA-256: `741e2c3b351ddf169a738da9f2c048608ff7f2c5cc02f1ebc6b118bb090d5d55`
- 원문: [MPL-2.0](libraries/certifi.txt)

- [동봉된 원본 소스](sources/certifi-2026.7.22.tar.gz): 공식 소스 배포본을 수정 없이 보관합니다.

`requirements/base.txt`에서 certifi를 2026.7.22로 고정합니다. 코드와 CA 인증서 데이터를
수정하지 않는 배포를 기준으로 하며, 원본 소스는 MPL-2.0으로 제공됩니다.
설정 → 프로그램 정보 → 라이브러리 → certifi의 **동봉된 원본 소스 저장** 버튼으로
인터넷 연결 없이 소스를 받을 수 있습니다. CLI 배포물에는 `resources/licenses/sources/`에
같은 파일이 포함됩니다(PyInstaller 내부 리소스 디렉터리 기준).

데스크톱 및 CLI spec은 `packaging/verify_certifi.py`를 실행해 설치 버전,
동봉 소스의 SHA-256, 라이선스 원문, 설치된 코드·인증서 데이터의 일치를 검사합니다.
불일치하면 빌드를 중단합니다. 별도 실행: `python packaging/verify_certifi.py`.

certifi를 업데이트할 때는 requirements, manifest, 원문, 소스 배포본과 이 문서를 함께
갱신해야 합니다. 인증서 데이터의 보안 업데이트를 막기 위한 고정이 아닙니다.
MPL 대상 파일을 수정하는 배포로 바꾸는 경우 수정 소스도 제공하고 검증 정책과 안내를
갱신해야 합니다. 이 소스 제공은 마음나래 자체 코드의 MIT 라이선스를 변경하지 않습니다.
[Mozilla 공식 FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)를 참고하세요.

## SQLCipher 및 네이티브 구성요소

SQLCipher Community Edition은 ZETETIC, LLC의 저작물입니다.
수록한 Community Edition 원문은 상용 에디션 계약을 대신하지 않습니다.
macOS 검증용 빌드의 SQLCipher 4.19.0 Community에는 OpenSSL 3.6.0이 정적으로 연결되어
있으며, Python TLS용 동적 OpenSSL 3.5.7과 구분하여 두 원문·저작권 고지를 수록했습니다.
다른 릴리스는 해당 빌드의 엔진·연결 라이브러리를 다시 확인해야 합니다.
[공식 에디션별 안내](https://www.zetetic.net/sqlcipher/license/)

## 네이티브·웹 자산 고지

CPython, OpenSSL, Zstandard, libuv, LibYAML 및 Rust 확장 내부 구성요소의 고지를 추가했습니다.
NiceGUI의 Vue·Quasar·AG Grid Community 외 웹 번들과 Google 웹 폰트도 포함합니다.
프로그램 정보의 라이브러리·폰트 항목에서 고지 전문을 읽을 수 있습니다.
[실제 파일별 근거와 검증 범위](NATIVE_WEB_AUDIT.md)를 참고하세요.

nh3 내부의 MPL 대상 cssparser·dtoa-short 원본 소스도 동봉하며 해당 항목에서 저장할 수 있습니다.
사용자가 수정한 경우에는 수정 소스도 함께 제공해야 합니다.

## 폰트와 설치 도구

번들 폰트와 파생 폰트는 각각의 OFL-1.1 원문을 유지하며 MIT로 재라이선스하지 않습니다.
현재 JournalSans·Ridi Batang 변환본의 이름·원 저작권 보존은 점검했습니다. 새 변환본은 다시 확인합니다.
Windows 설치 프로그램의 Inno Setup 번역 원문과 기존 라이선스는 저장소의
`packaging/languages/`에 있습니다. 실제 사용한 컴파일러 버전의 라이선스와 번역 파일
출처가 일치하는지 별도로 확인해야 합니다.

## 배포 전 남은 확인 사항

- OS별 실제 버전, 구성요소 목록과 위 참고 고지의 일치 여부
- 새 빌드의 JavaScript·CSS·아이콘 등이 이번 NiceGUI 스냅샷과 달라졌는지 여부
- 다른 OS의 네이티브 구성요소 확인. orjson macOS arm64 도구 체인·런타임 고지는
  [별도 점검 기록](ORJSON_TOOLCHAIN_AUDIT.md)에 따라 보완했으며, 새 빌드의 wheel이 달라지면 재확인
- LGPL/MPL 대상 소스의 실제 제공, 수정 내역, 재결합·재빌드 절차
- 설치된 앱과 CLI 번들에서 고지 원문과 소스 안내에 접근할 수 있는지 여부

## 로컬 AI

- **llama.cpp / GGML b12144:** MIT. 지원 플랫폼에 공식 엔진과 동적 라이브러리를 동봉합니다.
  원문: `libraries/llama-cpp.txt`, 고정 소스: https://github.com/ggml-org/llama.cpp/tree/b12144
- **EXAONE 4.0 1.2B:** 기본 추천 모델이며 가중치는 별도 다운로드입니다.
  EXAONE AI Model License Agreement 1.2 - NC 원문은 `libraries/exaone4-model.txt`에 포함합니다.
  비상업적 연구·교육 목적의 이용 조건을 확인하세요. 서버용 채팅 템플릿은 공식 저장소의
  revision `162446400ea4596377a3ce1d3ddffa32971af0a6`에서 가져왔습니다.
- **EXAONE 3.5 2.4B Instruct:** 추천 목록에서는 제외하며 기존 설치 모델의 고지를 유지합니다.
  EXAONE AI Model License Agreement 1.1 - NC 원문은 `libraries/exaone-model.txt`에 포함합니다.
  연구·평가·테스트 중심의 이용 조건이며 일반 상담 실무 이용 허용을 의미하지 않습니다.
- **Qwen3 4B GGUF:** Apache-2.0 모델의 별도 다운로드입니다.
  모델별 고정 revision과 원문 링크는 `resources/ai/models.json` 및 AI 설정 화면에 표시합니다.
- **httpx:** 기존 동봉 BSD-3-Clause 고지를 사용하며 로컬 HTTP/SSE와 모델 다운로드에 직접 사용합니다.

Windows 엔진의 `libomp.dll`에는 LLVM OpenMP 고지(`libraries/llvm-openmp.txt`)가,
엔진의 JSON 구성요소에는 nlohmann/json 고지(`llama-cpp/LICENSE-jsonhpp`)가 적용됩니다.
