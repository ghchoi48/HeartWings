# 마음나래 프로젝트 홈페이지

한국어 정적 홈페이지와 마음나래 사용 설명서 위키입니다. 홈페이지는 JavaScript 없이 동작하고, 위키는 검색과 선택적 스크린샷 표시에 작은 JavaScript를 사용합니다. 문서 본문과 탐색은 JavaScript 없이도 읽을 수 있습니다.

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
- `wiki/`: 사용 설명서 홈과 주제별 HTML 문서, 위키 전용 CSS·JavaScript와 검색 색인.
- `assets/wiki/`: 나중에 추가할 가상 데이터 스크린샷. [파일명별 촬영 안내](assets/wiki/README.md)에 맞는 PNG를 추가하면 해당 문서에 자동 표시됩니다. 파일이 없거나 손상된 경우 이미지 영역 전체를 숨깁니다.
- 다운로드는 GitHub의 `releases/latest`를 사용합니다. 지원 운영체제 안내는 실제 릴리스 파일이 바뀔 때 함께 갱신합니다.
- 공식 웹폰트: https://spoqa.github.io/spoqa-han-sans/css/SpoqaHanSansNeo.css. Regular(400), Bold(700)를 사용하며 외부 폰트를 불러오지 못하면 시스템 글꼴로 표시합니다. 폰트는 이 사이트에 재배포하지 않습니다.
- `assets/logo.png`는 프로젝트의 기존 로고입니다. `favicon.png`와 `share.png`도 기존 로고를 사용합니다.
- 앱 화면은 별도 데모 DB에 만든 가상 학생·상담 기록으로 촬영했습니다. 실제 학생 자료로 교체하지 마세요. 캡션과 대체 텍스트도 함께 갱신합니다.

## 변경 후 확인

### 위키 문서 관리

기존 `wiki/*.html`을 직접 편집합니다. 문서 본문은 `article`, 검색 단위는 고유 ID를 가진 `h2`로 구분합니다. ID는 외부 링크에 쓰이므로 가능하면 유지하세요. 새 문서를 추가할 때는 모든 문서의 문서 목록과 이전·다음 링크, 해당 문서의 목차·제목·설명·canonical·공유 메타데이터를 함께 갱신합니다. 모든 내부 경로는 상대 경로로 작성합니다.

본문을 변경한 뒤 저장소 루트에서 실행합니다.

```powershell
python scripts/generate_wiki_search.py
python scripts/generate_sitemap.py
```

두 생성 파일도 함께 커밋합니다. Pages 배포에서도 같은 스크립트를 실행하여 검색 색인과 사이트맵을 갱신합니다. Python 표준 라이브러리만 사용하며 추가 설치는 필요 없습니다. 검색은 정규화한 검색어를 공백으로 나눠 모든 단어를 포함한 절을 찾고 제목 일치를 우선합니다. 검색어는 서버로 전송하지 않습니다.

로컬 서버의 `/wiki/`에서 확인하세요. 검색 색인을 읽으므로 `file://`로 HTML을 직접 여는 대신 위의 HTTP 서버를 사용합니다. 검색 실패 시 문서 목록으로 이동할 수 있습니다. 스크린샷은 색인 재생성 없이 파일 추가만으로 나타납니다.

### 확인 항목

360px, 768px, 1440px에서 넘침과 줄바꿈을 확인합니다. 키보드 포커스, FAQ 펼치기, 원본 이미지 링크, 다운로드·문의 링크, 200% 확대, 외부 폰트 실패 시 대체 글꼴을 확인합니다. 하위 경로 배포를 위해 사이트 내부 링크와 자산은 상대 경로로 유지합니다.

위키는 `백업`, `집단 상담`, `학년도`, 복수 검색어와 결과 없는 검색, 검색 결과의 절 이동을 확인합니다. 이미지가 전혀 없을 때·일부만 있을 때·손상된 파일일 때의 표시, JavaScript 비활성 상태에서의 탐색도 확인합니다. `python scripts/check_wiki.py`로 문서 링크·색인·스크린샷 규약을 검사할 수 있습니다.
