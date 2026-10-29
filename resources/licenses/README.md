# 오픈소스 라이선스 고지

마음나래 자체 코드는 별도 표시된 부분을 제외하고 루트 `LICENSE`의 MIT 라이선스로 제공됩니다.
`maeumnarae/services/memory_xlsb.py`는 LGPL-3.0-or-later 파생 코드입니다.
서드파티 코드·폰트·네이티브 구성요소에는 각각의 라이선스가 적용되며,
이 프로젝트의 MIT 라이선스로 재라이선스되지 않습니다.

`manifest.json`의 `libraries`와 `fonts` 항목은 설정 → 프로그램 정보에 표시됩니다.
이 폴더 전체와 루트 `LICENSE`는 데스크톱 및 CLI PyInstaller 설정에 포함됩니다.
배포 및 소스 제공 안내는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인하세요.

## 수록 범위와 버전

직접 실행 의존성, macOS 검증용 빌드에서 식별한 Python 전이 의존성,
빌드·실행 파일 구성요소의 참고 고지 및
폰트 7개 항목(파생 폰트 및 NiceGUI 웹 폰트 포함)을 수록합니다. 전체 플랫폼의 배포물 목록은 아닙니다.

- `version`은 고지 대상 버전입니다. 이번에 대조한 5개 항목의 근거는 [버전 대조 기록](VERSION_AUDIT.md)에 있습니다.
- Pydantic 2.13.5, Pillow 12.3.0, FastAPI 0.141.1, Starlette 1.6.0의 원문은 현재 설치 배포본에서 가져왔습니다. Pillow는 배포본 LICENSE의 부속 라이브러리 고지도 보존합니다.
- SQLCipher Community 4.19.0 원문은 공식 고정 태그에서 가져왔고, 엔진 버전은 `PRAGMA cipher_version`으로 확인했습니다.
- 나머지 기존 원문은 설치 패키지에서, openpyxl·et_xmlfile 원문은 동일 버전 소스 배포본에서 가져왔습니다.
- PyInstaller의 `license_reference_version`은 참고 원문 버전입니다. 전체 배포 구성요소의 확인 완료를 의미하지 않습니다.
- pyxlsb에는 LGPL 및 GPL 본문을 함께 보관합니다. certifi·pyxlsb에는 기존 고지 버전의 공식 소스 배포본 링크를 추가했습니다.
- 폰트는 해당 원문과 출처를 유지합니다. 현재 파생 폰트의 예약 이름·내부 이름 확인 결과는 [네이티브·웹 점검 기록](NATIVE_WEB_AUDIT.md)에 있습니다. 파일이 바뀌면 다시 확인합니다.

Python 전이 의존성의 포함 근거·원문 출처와 재검증 방법은
[Python 의존성 점검 기록](PYTHON_DEPENDENCY_AUDIT.md)에 있습니다.

네이티브·웹 고지의 실제 파일 연결, 추가 원문, Rust·npm 구성요소 목록 및
남은 대응 확인 사항은 [네이티브·웹 점검 기록](NATIVE_WEB_AUDIT.md)에 있습니다.

orjson macOS arm64의 정확한 nightly 식별과 런타임 예외 고지 근거는
[orjson 도구 체인 점검 기록](ORJSON_TOOLCHAIN_AUDIT.md)에 있습니다.

## manifest 필드

- `name`: 표시 이름
- `license`: 라이선스 이름 또는 식별자; 복수 라이선스는 적용 범위 병기
- `source`: 공식 프로젝트 URL
- `version`: 고지 대상 패키지 또는 엔진 버전
- `license_reference_version`: 배포 버전 확인 전의 참고 원문 버전
- `license_source`: 공식 원문 또는 해당 버전 배포 페이지 URL
- `license_origin`: 설치 배포본에서 추출한 원문 경로(있는 경우)
- `license_sha256`: 수록한 원문 파일의 SHA-256
- `license_files`: 추가 수집한 개별 원문 경로·출처·SHA-256 목록
- `text_file`: 이 폴더 기준 UTF-8 라이선스 전문 파일의 상대 경로
- `source_archive`: 고지 버전에 대응하는 공식 원본 소스 배포본 URL
- `source_file`: 오프라인 저장을 지원하는 동봉 소스 파일의 상대 경로
- `source_sha256`: 동봉 소스 배포본의 SHA-256
- `modified_source_file`: 사용된 라이브러리·파생 구현 ZIP의 상대 경로
- `note`: 프로그램 정보에 표시할 적용 범위·확인 상태

## 릴리스 시 유지관리

1. 각 OS/CPU 빌드의 정확한 패키지 버전과 배포 파일 목록을 기록합니다.
2. 참고 원문을 실제 배포 버전의 원문으로 대조·교체하고 확인 상태를 갱신합니다.
3. 저작권 고지, 라이선스 본문, 필요한 NOTICE를 함께 보관합니다. 라이선스 이름만 기록하는 것으로 대체하지 않습니다.
4. 전이 의존성, 웹 번들, Python 런타임, 네이티브 라이브러리 및 설치 도구의 재배포 파일도 조사합니다.
5. LGPL/MPL 소스 및 재빌드 자료를 준비하고 다운로드 경로를 검증합니다.
6. 설치본의 프로그램 정보와 라이선스 파일을 열어 누락 여부를 확인합니다.

프로그램 정보는 `maeumnarae/core/program_info.py`에서 관리합니다.

certifi는 2026.7.22로 고정하고 원본 소스를 동봉합니다. 두 PyInstaller spec에서
`packaging/verify_certifi.py`로 설치 파일과 동봉 소스의 일치를 확인합니다.

pyxlsb의 기준 원본과 사용된 라이브러리·파생 구현 ZIP도 동봉합니다.
`python packaging/prepare_pyxlsb_sources.py`로 갱신하며 두 spec이 빌드 전에 실행합니다.
기준 원본은 고정 해시를 확인하지만 사용자 수정본은 차이를 기록하여 수록합니다.
ZIP은 앱 전체 재빌드 자료가 아니며 전체 소스·빌드 안내는 별도로 제공해야 합니다.
