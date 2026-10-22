# 오픈소스 라이선스 고지

`manifest.json`의 `libraries`와 `fonts` 목록에 등록한 항목을 설정 → 프로그램 정보에 표시합니다.
현재 목록은 직접 사용하는 런타임 라이브러리와 번들 폰트의 초기 목록입니다.
전이 의존성과 프런트엔드 번들 등 배포물에 포함되는 구성요소도 확인하여 추가할 수 있습니다.
전문을 아직 등록하지 않은 항목은 화면에서 준비 중으로 표시됩니다.

각 항목은 다음 필드를 지원합니다.

- `name`: 표시 이름 (필수)
- `license`: 확인한 라이선스 이름 또는 SPDX 식별자 (선택)
- `source`: 공식 프로젝트 URL (선택)
- `text_file`: `licenses` 폴더 기준 UTF-8 전문 파일의 상대 경로 (선택)

예를 들어 `libraries/example.txt`에 실제 배포 버전의 저작권 고지와 라이선스 전문을
그대로 보관한 뒤 다음과 같이 등록합니다.

```json
{
  "name": "Example Library",
  "license": "MIT",
  "source": "https://example.org/",
  "text_file": "libraries/example.txt"
}
```

여러 라이선스나 NOTICE가 필요하면 해당 파일의 고지를 빠짐없이 함께 수록합니다.
이 폴더 전체와 프로젝트 루트의 `LICENSE`는 PyInstaller 배포물에도 포함됩니다.
프로그램 이름, 제작자 이름, GitHub 주소는 `program_info.py`에서 수정합니다.
