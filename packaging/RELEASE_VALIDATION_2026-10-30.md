# 정식 macOS 산출물 검증 — 2026-10-30

대상: 마음나래 1.1.0 / macOS arm64 / Python 3.14.7.
결과: **자동 검증 및 macOS 네이티브 초기 화면 실행 통과**.
이 기록은 빌드 후 검증 증거이며, 대상 소스 ZIP 자체에는 포함되지 않습니다.

## 발견 사항과 조치

orjson workflow 근거 파일의 이름이 점으로 시작해 소스 ZIP 수집에서 제외되었습니다.
`assets/evidence/orjson-toolchain/github-workflows-artifact.yaml`로 이름을 변경하고,
증거 인벤토리를 갱신한 뒤 정식 재빌드했습니다. 최종 검증은 모두 새 산출물 기준입니다.
이전 2단계 산출물 대신 현재 `dist/release/`의 세 파일을 사용하세요.

## 통과한 검사

- 실행 파일 ZIP·대응 소스 ZIP·내부 build-environment·소스 1521개 해시 일치
- 실행 파일에 동봉된 라이선스·증거·소스 파일 1,355개와 대응 소스 ZIP의 파일 집합 및 바이트 일치
- 고지 110개와 참조 원문·동봉 원본 소스·증거의 해시/존재 확인
- Python 배포 패키지 71개 버전 및 고지 대조
- 네이티브 125개, 웹 430개, 폰트 10개 대조. 이전 감사 대비 charset-normalizer 네이티브 2개 추가,
  실행 파일 본체 변경, 나머지 기존 자산 해시 동일. 신규 네이티브 코드와 설치 wheel 코드 일치
- orjson 코드 및 새 런타임 고지 확인. 외부 절대 경로 의존성은 macOS 시스템 경로만 확인
- 공식 pyxlsb 1.0.10 및 동봉 사용 소스의 원본 변경 파일 없음
- 빌드 위치 및 ZIP 재배치 위치의 frozen 검증 결과 동일
- 합성 XLSB: 인적사항 7행의 학생 1명, 상담대장 6행의 상담 1건, 날짜 경계값·이관 지문 일치
- 실제 frozen 실행 파일에서 손상 XLSB 거부, 소스 ZIP 해시 변조 거부
- `codesign --verify --deep --strict` 통과
- 테스트 32개 및 하위 사례 15개 통과
- 재배치한 macOS 네이티브 창에서 최초 실행 화면 정상 렌더링 확인 및 종료 확인

이관 지문: `d0872a7373f2d681a9ab815ff014b129b2d2dfc4d40380586db95d4e779d7c27`.
사용자 DB는 열지 않았으며, 네이티브 기동에는 `build/release-validation/ui-test/synthetic.db` 경로를 지정했습니다.

## 최종 파일과 SHA-256

- `dist/release/maeumnarae-macos.zip`
  `ce914e63edba939a0d9da5724e4408df48b6cd3b6d20237318018adcc1cc7192`
- `dist/release/maeumnarae-1.1.0-darwin-arm64-sources.zip`
  `4ceb9895ef9b75a93b4d1d6828925fd977e4bf014bd4d9186f4ed9906121bb04`
- `dist/release/maeumnarae-1.1.0-darwin-arm64-release.json`
  `f9c7cfa71ab6120959894e94d33cc808ebfdff001d67d4fe231c3b469c0546c8`

## 증거와 재검증

`build/release-validation/`:

- `summary.json`: 검증 요약 및 증거 JSON 해시
- `materials-check.json`, `asset-inventory.json`, `native-linkage.json`, `python-inventory.json`
- `frozen-check.json`, `relocated-check.json`, `corrupt-check.json`, `release-check.json`
- `rebuild.log`, `native-startup.log`
- `audit_final.py`: 고지·소스 전체 대조 및 구성요소 검증 절차
- `negative_checks.py`: 손상 입력 및 해시 변조 거부 절차

```sh
build/release-venv/bin/python packaging/check_release.py \
  dist/release/maeumnarae-1.1.0-darwin-arm64-release.json \
  --frozen-report build/release-validation/relocated-check.json
```

동봉 ASSET_INVENTORY/PYTHON_BUNDLE_INVENTORY는 이전 검증용 ZIP에 대한 역사적 근거입니다.
정식 산출물의 인벤토리는 위 `build/release-validation/` 파일들에 별도로 기록했습니다.
검증 결과를 실행 파일 안에 소급 삽입하여 검증 대상 해시를 바꾸지 않았습니다.

## 범위의 한계 / 4단계

frozen 실행 파일의 XLSB 읽기·모델 변환·지문까지 검증했습니다.
GUI 업로드부터 실제 DB 저장까지의 전체 이관 및 네이티브 소스 저장 대화상자는 미검증입니다.
초기 화면 이후의 온보딩 전체 흐름은 검증하지 않았습니다.
개발자 서명·공증·Gatekeeper, Windows/Linux, 다양한 실제 Excel 자료 및 1904 날짜 체계는 별도입니다.

4단계에서는 위 실행 파일 ZIP·대응 소스 ZIP·릴리스 JSON과 재빌드 안내를 함께 제공해야 합니다.
소스 ZIP에 BUILDING.md가 포함된 것은 확인했으며 외부 게시·배포는 수행하지 않았습니다.
