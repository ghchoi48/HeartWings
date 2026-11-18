# 마음나래 프로젝트 홈페이지

빌드 도구나 JavaScript 없이 제공하는 한국어 정적 홈페이지입니다.

## 로컬 미리보기

저장소 루트에서 `python -m http.server 8000 --bind 127.0.0.1 --directory website`를 실행하고 `http://127.0.0.1:8000/`을 엽니다.

## GitHub Pages 배포

1. 저장소 Settings → Pages → Build and deployment → Source에서 **GitHub Actions**를 선택합니다.
2. 사이트와 `.github/workflows/pages.yml`을 `main`에 반영합니다.
3. Actions의 **Deploy project homepage** 성공과 `https://ghchoi48.github.io/HeartWings/`을 확인합니다. 수동 실행도 지원합니다.

워크플로는 `website/`만 업로드합니다. 앱 데이터베이스, 개발 환경, 설치 파일은 홈페이지에 포함하지 않습니다. Pages 배포는 저장소 권한과 GitHub Pages 사용 가능 여부에 따라 최초 설정이 필요합니다.

## 콘텐츠 관리

- `index.html`: 소개, FAQ, 다운로드 링크, 검색·공유 메타데이터.
- `styles.css`: 반응형 레이아웃과 색상·글꼴.
- 다운로드는 GitHub의 `releases/latest`를 사용합니다. 지원 운영체제 안내는 실제 릴리스 파일이 바뀔 때 함께 갱신합니다.
- 공식 웹폰트: https://spoqa.github.io/spoqa-han-sans/css/SpoqaHanSansNeo.css. Regular(400), Bold(700)를 사용하며 외부 폰트를 불러오지 못하면 시스템 글꼴로 표시합니다. 폰트는 이 사이트에 재배포하지 않습니다.
- `assets/logo.png`는 프로젝트의 기존 로고입니다. `favicon.png`와 `share.png`도 기존 로고를 사용합니다.
- 앱 화면은 별도 데모 DB에 만든 가상 학생·상담 기록으로 촬영했습니다. 실제 학생 자료로 교체하지 마세요. 캡션과 대체 텍스트도 함께 갱신합니다.

## 변경 후 확인

360px, 768px, 1440px에서 넘침과 줄바꿈을 확인합니다. 키보드 포커스, FAQ 펼치기, 원본 이미지 링크, 다운로드·문의 링크, 200% 확대, 외부 폰트 실패 시 대체 글꼴을 확인합니다. 하위 경로 배포를 위해 사이트 내부 링크와 자산은 상대 경로로 유지합니다.
