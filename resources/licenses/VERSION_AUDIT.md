# 고지 버전 대조 기록

확인일: 2026-10-29. 범위: 앞선 점검에서 버전 차이가 확인된 5개 구성요소.

## 기준과 결과

- Python 3.14.7 / macOS arm64의 현재 설치 배포본과 기존 검증용 릴리스 JSON의 버전을 대조했습니다.
- 기준 기록: `dist/validation-macos/maeumnarae-1.1.0-darwin-arm64-release.json`의 `environment.packages` 및 `environment.native_versions`.
- 아래 5개 항목 모두 버전, 수록 원문 바이트 및 manifest의 SHA-256 검사를 통과했습니다.
- Pydantic·FastAPI·Starlette 원문은 기존 파일과 동일했습니다. 버전 및 출처 기록을 정정했습니다.
- Pillow는 설치 배포본의 전체 LICENSE로 교체했습니다. Pillow 자체 저작권 및 부속 라이브러리 고지를 생략하지 않았습니다.
- SQLCipher는 v4.19.0 공식 LICENSE.md로 교체했습니다. 저작권 표시는 `Copyright (c) 2025, ZETETIC LLC`입니다.

| 구성요소 | 이전 고지 | 대조한 버전 |
|---|---|---|
| Pydantic | 2.14.1 | 2.13.5 |
| Pillow | 12.0.0 | 12.3.0 |
| FastAPI | 0.162.0 | 0.141.1 |
| Starlette | 1.10.0 | 1.6.0 |
| SQLCipher Community | 4.6.1 | 4.19.0 community |

## 원문 근거

### Pydantic 2.13.5

- 출처: https://pypi.org/project/pydantic/2.13.5/
- 수록 파일: `libraries/pydantic.txt`
- SHA-256: `a9e186f3ca16b5eef84318e7a701721351a00cb7b8ae3a4394b67b49e3529ef3`
- 설치 배포본 내부 경로: `pydantic-2.13.5.dist-info/licenses/LICENSE`

### pillow 12.3.0

- 출처: https://pypi.org/project/pillow/12.3.0/
- 수록 파일: `libraries/pillow.txt`
- SHA-256: `dda12a98c1979cf3d94df1cff45d27a4cb3f04a60c76f76902ac54cac03ec0ce`
- 설치 배포본 내부 경로: `pillow-12.3.0.dist-info/licenses/LICENSE`

### SQLCipher Community Edition 4.19.0

- 출처: https://raw.githubusercontent.com/sqlcipher/sqlcipher/v4.19.0/LICENSE.md
- 수록 파일: `libraries/sqlcipher.txt`
- SHA-256: `2a2826f6acf46fa650730cf42cbb22a642be33a7ef119c9c4f4bf6daf3bef48e`

### fastapi 0.141.1

- 출처: https://pypi.org/project/fastapi/0.141.1/
- 수록 파일: `libraries/fastapi.txt`
- SHA-256: `4ec89ffc81485b97fec584b2d4a961032eeffe834453894fd9c1274906cc744e`
- 설치 배포본 내부 경로: `fastapi-0.141.1.dist-info/licenses/LICENSE`

### starlette 1.6.0

- 출처: https://pypi.org/project/starlette/1.6.0/
- 수록 파일: `libraries/starlette.txt`
- SHA-256: `dcb95677a02240243187e964f941847d19b17821cf99e5afae684fab328c19bf`
- 설치 배포본 내부 경로: `starlette-1.6.0.dist-info/licenses/LICENSE.md`

## 다음 빌드에서 확인할 사항

이번 변경은 저장소의 고지를 갱신한 것입니다. 기존 검증용 실행 파일·소스 ZIP·릴리스 JSON은
과거 검증 근거로 그대로 보존했으며, 그 안의 고지가 소급하여 갱신되지는 않습니다.
새 실행 파일과 대응 소스 ZIP을 생성해야 변경된 고지가 포함됩니다.

requirements의 버전 범위는 변경하지 않았습니다. 릴리스마다 실제 설치 버전·원문을 다시
대조하고 달라진 항목의 manifest, 원문 및 기록을 함께 갱신해야 합니다.
Pillow 원문은 이번 macOS 설치 배포본 기준이므로 다른 OS의 wheel도 별도로 대조해야 합니다.

전이 의존성 전체 목록, SQLCipher에 연결된 OpenSSL 등 네이티브 구성요소, NiceGUI 웹 자산과
폰트 예약 이름 점검은 후속 단계입니다. 이 기록은 정식 배포 승인이나 전체 고지 완료를 뜻하지 않습니다.
