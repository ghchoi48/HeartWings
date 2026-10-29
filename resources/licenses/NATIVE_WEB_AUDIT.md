# 네이티브·웹 자산 고지 점검

점검: 2026-10-29~30. 대상: 기존 macOS arm64 검증용 `maeumnarae-macos.zip`.
이 기록은 고지 자료 보완이며, 정식 배포 승인이나 새 실행 파일의 검증 기록이 아닙니다.
기존 검증용 앱·ZIP·대응 소스 ZIP은 변경하지 않았습니다.

## 실제 파일과 고지 연결

- 네이티브 파일 **123개**: 확장 모듈, dylib, CPython 런타임 및 PyInstaller 실행 파일
- NiceGUI 웹 자산 **430개**: JavaScript, CSS, 이미지, 폰트 및 JSON 자료
- 앱 폰트 **10개**: 원본 폰트와 두 파생 폰트의 Regular/Bold 파일
- 추가한 프로그램 정보 항목 **30개**: 네이티브·웹 고지 28개, 웹 폰트 고지 2개

[ASSET_INVENTORY.json](ASSET_INVENTORY.json)에 파일별 SHA-256, 고지 항목,
폰트 이름 테이블과 증거 파일 해시를 기록했습니다. ZIP의 실제 파일만 조사하고
macOS 메타데이터와 심볼릭 링크의 중복 경로는 제외했습니다.
NiceGUI 웹 파일과 앱 폰트는 현재 설치본·저장소 파일과 바이트 단위로 대조했습니다.

원문 출처와 원문 파일별 해시는 manifest의 `license_files`에 있으며,
`assets/`에 원문을 보존하고 `libraries/`·`fonts/`에 화면 표시용 합본을 연결했습니다.

## 네이티브 구성요소

| 구성요소 | 확인 버전 | 근거 및 고지 |
|---|---|---|
| Python TLS용 OpenSSL | 3.5.7 | 번들 libcrypto 문자열, Python ssl 버전, 공식 태그의 LICENSE·저작권 헤더 |
| SQLCipher용 OpenSSL | 3.6.0 | cipher_provider_version, 번들 확장 문자열, 공식 태그의 LICENSE·저작권 헤더 |
| CPython | 3.14.7 | 기존 릴리스 기록 및 설치 런타임 LICENSE·라이선스 문서 |
| Zstandard | 1.5.7 | libzstd의 Mach-O 버전, 공식 LICENSE·COPYING |
| libuv | 1.48.0 | uvloop.libuv_get_version, 0.22.1 공식 소스의 버전 헤더·LICENSE·LICENSE-extra·LICENSE-docs |
| LibYAML | 0.2.5 | yaml._yaml.get_version_string, 공식 태그 License |
| Pillow 부속 라이브러리 | Pillow 12.3.0 wheel 기준 | 이전 단계에서 보존한 wheel 전체 LICENSE에 연결; 각 바이너리 해시 기록 |

**SQLCipher의 OpenSSL을 Python의 OpenSSL과 혼동하지 않았습니다.**
SQLCipher 확장의 `otool -L`에는 libcrypto 동적 연결이 없고, provider 버전은
`OpenSSL 3.6.0 1 Oct 2025`입니다. 별도의 libcrypto.3.dylib에는
`OpenSSL 3.5.7 9 Jun 2026` 문자열이 있습니다.

Pillow의 부속 dylib에는 Brotli, LittleCMS, libpng, libxcb, libjpeg-turbo,
FreeType, HarfBuzz, libwebp/sharpyuv, OpenJPEG, libavif, zlib-ng, libXau,
xz/liblzma, libtiff가 있습니다. 개별 dylib의 ABI 번호를 프로젝트 릴리스 버전으로
추정하지 않았습니다. 해당 wheel의 부속 고지 전체를 보존합니다.
시스템의 `/usr/lib`·`/System/Library` 연결 경로는 앱이 재배포한 파일로 세지 않았습니다.

[`native-linkage.json`](assets/evidence/native-linkage.json)에 `otool -L` 결과가 있습니다.
nh3, pydantic_core, watchfiles, orjson, sqlcipher3, yaml, uvloop의 **7개 arm64 코드 섹션**이
설치 확장과 검증용 번들에서 동일한 것도 확인했습니다. 서명·로드 명령 변경이 가능한
Mach-O 전체 파일 해시 대신 `__TEXT,__text` 출력을 비교한 것입니다.
[`native-versions.json`](assets/evidence/native-versions.json)에 실제 조회한 버전을 기록했습니다.

## Rust 확장 내부 구성요소

설치 wheel이 제공한 CycloneDX SBOM을 `assets/evidence/*-wheel-sbom.json`에 보존했습니다.
nh3·pydantic_core·watchfiles·orjson에 대해 **199개 crate/버전 조합**의 공식 원본을
SBOM의 SHA-256과 대조하고 LICENSE·NOTICE·COPYRIGHT 등을 수집했습니다.
이 숫자는 SBOM의 보수적인 고지 범위이며, 빌드 도구나 다른 target 전용 항목도 포함할 수 있습니다.
정확히 199개가 모두 실행 파일에 링크되었다고 주장하지 않습니다.

- MPL-2.0인 cssparser 0.37.0과 dtoa-short 0.3.5의 공식 `.crate` 원본도 `sources/`에 동봉했습니다.
  프로그램 정보에서 인터넷 없이 저장할 수 있습니다. 수정 배포에는 실제 수정한 소스가 필요합니다.
- orjson 소스 배포본의 vendored 구성요소 고지도 추가로 보존했습니다.
- nh3·pydantic_core·watchfiles 바이너리에 남아 있는 Rust 컴파일러 커밋에 대응하는
  Rust LICENSE-MIT·LICENSE-APACHE·COPYRIGHT를 보존했습니다.
- orjson macOS arm64 공식 wheel과 설치 확장의 일치 및 PyPI 배포 출처를 대조하여
  `nightly-2026-08-01` / `ad3d0bc141a02cf446e384136d250a1f6950fed5`를 식별했습니다.
  표준 라이브러리 상세 고지와 compiler-builtins LLVM 예외를 추가했습니다.
  확인 수준과 재빌드 조건은 [orjson 도구 체인 점검](ORJSON_TOOLCHAIN_AUDIT.md)을 참고하세요.
  정확한 대응 확인에는 wheel 제작 기록이나 도구 체인을 기록한 재빌드가 필요합니다.

## NiceGUI 웹 자산

NiceGUI 3.18.0 공식 태그의 루트 잠금 파일과 실제 설치·번들에 포함된 요소별 잠금 파일을
보존했습니다. `dev` 전용 항목과 타입 선언 전용 `@types/*`를 제외한 **581개 npm 패키지/버전 조합**을
공식 배포본의 integrity 값으로 검증해 고지 자료를 수집했습니다.
이 역시 잠금 파일의 보수적인 범위이며 트리 셰이킹으로 제외되는 코드나 서버·빌드 경로도 포함할 수 있습니다.

| 주요 자산 | 고지 대상 버전 |
|---|---|
| Vue | 3.5.22 |
| Quasar | 2.18.5 |
| AG Grid Community | 34.2.0 |
| Socket.IO | 4.8.1 |
| Tailwind browser | 4.1.13 |
| UnoCSS runtime | 66.6.0 |
| Sass | 1.94.0 |
| DOMPurify | 3.4.16 |
| ECharts | 6.1.0 |
| Plotly.js | 3.1.1 |
| Mermaid | 11.16.1 |
| CodeMirror | 6.0.2 |
| xterm | 5.5.0 |
| Leaflet | 1.9.4 |
| Three.js | 0.180.0 |

8개 핵심 정적 파일은 npm 원본과 SHA-256이 그대로 일치합니다. 나머지 변환·번들 파일은
NiceGUI 배포본의 동일 파일 해시 및 동봉 잠금 파일을 근거로 고지를 연결했습니다.
상세 버전, 출처, integrity 및 원문 경로는 [ASSET_COMPONENTS.json](ASSET_COMPONENTS.json)에 있습니다.

- 배포본에 원문이 없는 경우 해당 npm 버전의 `gitHead` 고정 커밋에서 추가 수집했습니다.
- 34개 항목은 upstream이 README·메타데이터·소스 주석으로 고지를 제공하는 형태입니다.
  그 자료를 보존하고 표시된 라이선스의 표준 약관을 별도 항목에 추가했습니다.
  표준 템플릿의 저작권 자리표시자는 실제 저작권 표시가 아니며, 각 원문의 저작권·작성자 정보를 따릅니다.
- `@mapbox/jsonlint-lines-primitives`는 해당 배포본의 라이선스 필드가 없어
  공식 저장소의 고정 커밋 LICENSE를 보충 자료로 기록했습니다. 원래 배포본에 있던 파일로 가장하지 않습니다.
- DOMPurify의 Apache-2.0 또는 MPL-2.0 원문을 모두 보존하며 Apache-2.0 선택에 따른 고지를 제공합니다.
- Font Awesome의 MIT·CC-BY-4.0 고지 및 CC-BY-4.0 전문을 포함합니다.
- NiceGUI의 anywidget 파생 helper는 별도 원문과 소스 스냅샷을 보존했습니다.
  upstream 버전이 명시되어 있지 않아 임의의 anywidget 릴리스 번호를 붙이지 않았습니다.

## 폰트 이름과 원문

NiceGUI의 WOFF2 16개에서 이름·저작권 테이블을 읽었습니다.
Roboto 계열에는 해당 공식 프로젝트의 OFL-1.1 원문을, Material Icons·Material Symbols에는
공식 프로젝트의 Apache-2.0 원문을 추가했습니다. 각 실제 폰트의 저작권 문자열도 보존했습니다.
[Material Icons 공식 안내](https://developers.google.com/fonts/docs/material_icons),
[Material Symbols 공식 안내](https://developers.google.com/fonts/docs/material_symbols).

변환 폰트의 family(1), full name(4), PostScript(6), typographic family(16) 이름을 확인했습니다.

| 파생 폰트 | 실제 family 이름 | 원문 저작권 및 예약 이름 |
|---|---|---|
| JournalSans Regular/Bold | HeartWings Journal Sans | Adobe 저작권 및 예약 이름 Source를 저작권 필드에 보존; primary font name으로 사용하지 않음 |
| RIDIBatang TTF 변환본 | HeartWings Ridi Batang | RIDI & Sandoll 저작권 보존; 수록 OFL 저작권 머리말에 별도 예약 이름 선언 없음 |

따라서 이번 파일들의 파생 폰트 이름 확인은 마쳤습니다. 새로운 변환·교체 파일에는 다시 적용해야 합니다.
폰트의 모든 조항에 대한 법률 검토 완료나, 이름 확인만으로 전체 재배포 조건이 충족된다는 뜻은 아닙니다.

## 재검증

```sh
python packaging/audit_asset_notices.py --archive dist/validation-macos/maeumnarae-macos.zip
python -m pytest -q tests/test_asset_notices.py tests/test_python_notices.py tests/test_release_sources.py
```

최종 결과: 실제 ZIP의 파일·고지 검사 통과, 관련 테스트 **10개 통과**, `git diff --check` 통과.
새 고지·소스·증거 파일 **1,152개**가 릴리스 소스 수집기에 포함되는 것도 확인했습니다.
프로그램 정보에서 라이브러리 101개 항목과 폰트 7개 항목의 원문을 읽을 수 있습니다.
실제 GUI 클릭이나 실행 파일 재빌드는 수행하지 않았습니다.

검증 도구는 파일 누락·해시 변조·고지 연결 누락을 검사합니다. 다른 ZIP을 기존 결과로 통과시키지 않습니다.
`--archive`를 생략하면 동봉 원문·소스·증거 자료의 무결성만 검사합니다.
폰트 이름은 검증된 파일 해시에 묶인 기록을 검사하며, 검사 도구를 실행할 때마다 이름을 다시 파싱하지는 않습니다.

폰트 분석 도구(fontTools·Brotli)는 임시 폴더에서만 사용했습니다. 앱 의존성은 변경하지 않았습니다.
새 빌드나 다른 OS는 실제 파일을 다시 조사해 이 기록과 고지를 갱신해야 합니다.
Windows·Linux, Inno Setup, 설치·서명·공증, 새 실행 파일에서의 고지 화면 조작은 이번 검증 범위가 아닙니다.
