# orjson Rust 도구 체인·런타임 고지 확인

확인일: 2026-10-30. 대상은 현재 설치된 **orjson 3.12.0 / CPython 3.14 /
macOS arm64**와 기존 `dist/validation-macos/maeumnarae-macos.zip`입니다.
정식 재빌드·최종 산출물 검증·배포는 이 기록의 범위가 아닙니다.

## 확인 결과와 근거

- 공식 wheel: `orjson-3.12.0-cp314-cp314-macosx_15_0_arm64.whl`
- wheel SHA-256: `8c3bb86dd10f39b3fbf434b7d5dc7cac77d6fc8ac572ae30a10731ede2c4b647`
- wheel 내부 확장과 설치된 확장의 SHA-256이 동일합니다:
  `aaebbe8aad399489acc642c23615bd373192904c319f159496ea5ab0d3c3bc45`.
- 설치 확장의 arm64 `__TEXT,__text`에 대한 기존 `otool` 출력 해시와
  `assets/evidence/native-linkage.json`의 기존 번들 비교 기록도 일치합니다.
  이 출력 해시와 `verification.json`의 원시 코드 바이트 해시는 계산 방식이 다릅니다.
- PyPI HTTPS provenance의 subject digest는 wheel 해시와 일치합니다.
  인증서에는 소스 커밋 `6737895a1a4e3e26df0569a40147893a786f9a58`,
  `refs/tags/3.12.0`, `artifact.yaml`, 실행 번호 `31816598288`이 기록되어 있습니다.
- 해당 **불변 커밋**의 workflow와 `ci/macos.sh`, `ci/config.toml`을 확인했습니다.
  macOS arm64 빌드는 `nightly-2026-08-01`, `aarch64-apple-darwin`,
  `generic_simd,no_panic,optimize`, `panic=immediate-abort`를 사용합니다.
  `build-std` 대상은 `core,std,alloc,proc_macro,panic_abort`입니다.
- Rust 공식 2026-08-01 배포 manifest에서 도구 체인을 다음과 같이 식별했습니다:
  **rustc 1.99.0-nightly (ad3d0bc14 2026-07-31)**,
  커밋 **`ad3d0bc141a02cf446e384136d250a1f6950fed5`**.
  최소 지원 버전인 Rust 1.95와 wheel 제작 도구 체인은 구분합니다.

근거 원본과 해시는 `assets/evidence/orjson-toolchain/` 및
`ASSET_INVENTORY.json`에 저장했습니다. 기존 `rust-toolchains.json`은 바이너리 문자열
추출 결과이므로 orjson의 빈 배열을 그대로 유지합니다. wheel 자체는 고지에 중복 동봉하지 않습니다.

공식 출처:

- [PyPI 3.12.0](https://pypi.org/project/orjson/3.12.0/)
- [고정 커밋의 빌드 workflow](https://github.com/ijl/orjson/blob/6737895a1a4e3e26df0569a40147893a786f9a58/.github/workflows/artifact.yaml)
- [Rust nightly 배포 manifest](https://static.rust-lang.org/dist/2026-08-01/channel-rust-nightly.toml)

## 런타임 예외 고지 대응

공식 Rust manifest의 SHA-256으로 rustc 배포 압축 파일을 검증한 뒤,
그 안의 **COPYRIGHT-library.html**을 원형 그대로 보존했습니다.
이는 표준 라이브러리의 내부 파일과 외부 의존성에 대한 상세 저작권·라이선스 고지입니다.
공통 `COPYRIGHT`, `LICENSE-MIT`, `LICENSE-APACHE`만으로 대체하지 않습니다.

`assets/native/rust-runtime/ad3d0bc141a02cf446e384136d250a1f6950fed5/`에
원문을 저장하고, 앱에서 읽을 수 있도록 `libraries/orjson-rust-runtime-notices.txt`에
상세 HTML의 텍스트와 다음 원문을 함께 수록했습니다.

- Rust 공통 MIT / Apache-2.0 및 COPYRIGHT
- Unicode-3.0 본문과 상세 고지의 Unicode 저작권
- BSD-2-Clause 본문: 상세 고지에 포함된 Fuchsia 등 다른 대상의 예외도 보수적으로 보존
- compiler-builtins의 `LICENSE.txt`: **MIT AND Apache-2.0 WITH LLVM-exception**과
  LLVM 예외 전문. libm의 MIT 및 기여 코드의 선택 조건도 원문대로 유지

LLVM 예외는 컴파일 결과에 삽입되는 대상 코드에 대한 조건부 예외입니다.
이를 orjson 전체나 MPL 대상 코드의 의무 면제로 취급하지 않습니다.
기존 orjson MPL 원문·vendored 고지·대응 소스는 계속 유지합니다.
전체 대상의 표준 라이브러리 고지를 보수적으로 동봉하며, 모든 나열 항목이
이 macOS 바이너리에 실제 링크되었다는 뜻은 아닙니다.

## 확인 수준과 다음 빌드의 조건

정확한 nightly 식별은 공식 배포 provenance와 고정 workflow에 근거합니다.
바이너리 자체의 컴파일러 문자열이나 보존된 `rustc -Vv` 실행 로그에 의한 확인은 아닙니다.
PyPI에서 받은 증명의 내용·해시·인증서 필드는 대조했지만 독립적인 Sigstore
서명 체인·투명성 로그 검증 또는 비트 단위 재현 빌드는 수행하지 않았습니다.

다음 정식 빌드가 동일 wheel을 사용하면 이 도구 체인 고지를 사용할 수 있습니다.
다른 wheel·OS·CPU·버전 또는 소스 빌드로 바뀌면 그 빌드 출처와 런타임 고지를 다시
확인해야 합니다. 최종 실행 파일에 새 고지가 실제 포함되는지는 3단계에서 검증합니다.

오프라인 고지·증거 파일 무결성과 기존 검증용 ZIP 대조 (모두 통과):

```sh
python3 packaging/audit_asset_notices.py --archive dist/validation-macos/maeumnarae-macos.zip
python3 packaging/audit_python_notices.py \
  --archive dist/validation-macos/maeumnarae-macos.zip \
  --release dist/validation-macos/maeumnarae-1.1.0-darwin-arm64-release.json
```
