# 프로젝트 폴더와 파일 안내

실행 명령은 프로젝트 루트에서 수행합니다. 개발 중 변경된 파일도 현재 내용을 유지한 채 이동했습니다.

## 폴더별 역할

| 폴더 | 목적 |
| --- | --- |
| `maeumnarae/core/` | DB 연결·입력 모델·환경 설정·OS 연동·공통 리소스 경로 |
| `maeumnarae/repositories/` | 기능별 DB 조회·변경과 트랜잭션 |
| `maeumnarae/services/` | 외부 연동, 파일 변환, 백업·복원, 집계 |
| `maeumnarae/views/` | 페이지와 UI 구성·상호작용 |
| `maeumnarae/widgets/` | 홈 화면의 독립 위젯 |
| `resources/` | 앱에 함께 배포되는 읽기 전용 아이콘·글꼴·서식·라이선스 |
| `requirements/`, `packaging/`, `scripts/` | 의존성 정의, 번들 설정, 빌드 실행 자동화 |
| `tests/`, `docs/`, `artifacts/` | 검증 코드, 개발·사용 문서, 검증 결과 및 디자인 기록 |
| `.git/` | Git 이력과 내부 상태; 직접 이동·편집하지 않음 |
| `.venv/` | 로컬 Python 환경; 경로 의존성이 있으므로 위치 유지 |
| `build/`, `dist/` | 기존 빌드 중간 파일과 배포본; 새 구조 반영에는 재빌드 필요 |
| `__pycache__/`, `.pytest_cache/` | Python·pytest가 자동 생성하는 캐시 |
| `.DS_Store` | macOS Finder가 생성하는 메타데이터; Git 제외 |

사용자 DB·백업·설정·운영 로그는 기존 OS별 사용자 데이터 폴더에 계속 저장됩니다.
`maeumnarae/core/paths.py`가 소스 실행과 번들의 리소스 기준 경로를 관리합니다.
새 코드는 `from maeumnarae...` 형태로 가져옵니다. 버전은 `maeumnarae/core/program_info.py`에서 변경합니다.

## 실행 진입점 및 프로젝트 설정

| 파일 | 목적·용도 |
| --- | --- |
| [`main.py`](../main.py) | 데스크톱·브라우저 앱 실행; frozen 자식 프로세스 분기. |
| [`init_db.py`](../init_db.py) | 암호화 DB 초기화/확인 명령 실행. |
| [`README.md`](../README.md) | 설치, 실행 및 기능 사용 안내. |
| [`LICENSE`](../LICENSE) | 프로젝트 자체의 MIT 라이선스. |
| [`.gitignore`](../.gitignore) | 가상환경, 캐시, DB, 비밀 설정, 빌드 산출물을 버전 관리에서 제외. |
| [`.gitattributes`](../.gitattributes) | 텍스트 파일 줄바꿈 정규화. |

## 애플리케이션 소스

| 파일 | 목적·용도 |
| --- | --- |
| [`maeumnarae/__init__.py`](../maeumnarae/__init__.py) | 마음나래 애플리케이션 패키지. |
| [`maeumnarae/application.py`](../maeumnarae/application.py) | 마음나래 페이지 구성과 데스크톱·브라우저 실행 설정. |
| [`maeumnarae/cli.py`](../maeumnarae/cli.py) | 1단계 데이터 계층의 수동 실행 도구. 비밀번호는 터미널에서만 입력한다. |
| [`maeumnarae/core/__init__.py`](../maeumnarae/core/__init__.py) | 마음나래 공통 기반 모듈. |
| [`maeumnarae/core/app_fonts.py`](../maeumnarae/core/app_fonts.py) | 번들 fonts 폴더의 글꼴 목록과 브라우저용 @font-face 정의. |
| [`maeumnarae/core/database.py`](../maeumnarae/core/database.py) | SQLCipher 연결, 트랜잭션 및 스키마 관리. 평문 SQLite 대체는 금지한다. |
| [`maeumnarae/core/desktop.py`](../maeumnarae/core/desktop.py) | 네이티브 창 설정과 운영 로그. DB·화면 비즈니스 로직과 분리한다. |
| [`maeumnarae/core/models.py`](../maeumnarae/core/models.py) | UI나 DB 드라이버에 의존하지 않는 입력 및 저장 데이터 모델. |
| [`maeumnarae/core/paths.py`](../maeumnarae/core/paths.py) | 소스 실행과 PyInstaller 번들에서 동일하게 쓰는 읽기 전용 리소스 경로. |
| [`maeumnarae/core/program_info.py`](../maeumnarae/core/program_info.py) | 프로그램 소개 정보와 배포에 포함되는 라이선스 자료. |
| [`maeumnarae/core/settings_store.py`](../maeumnarae/core/settings_store.py) | 화면 설정과 위젯이 공유하는 JSON 파일의 원자적 읽기·수정·저장. |
| [`maeumnarae/repositories/__init__.py`](../maeumnarae/repositories/__init__.py) | UI는 이 계층의 API를 통해서만 학생/상담 데이터를 읽고 쓴다. |
| [`maeumnarae/repositories/_support.py`](../maeumnarae/repositories/_support.py) | 저장소 내부의 날짜 직렬화와 페이지 검증. |
| [`maeumnarae/repositories/attachment_repo.py`](../maeumnarae/repositories/attachment_repo.py) | 파일 본문을 암호화 DB에 저장하며 일지별 접근 범위를 검증한다. |
| [`maeumnarae/repositories/calendar_repo.py`](../maeumnarae/repositories/calendar_repo.py) | 캘린더 설정과 사용자 일정, 개인상담·집단상담·자문·특별교육 일정의 통합 조회. |
| [`maeumnarae/repositories/case_repo.py`](../maeumnarae/repositories/case_repo.py) | 상담 사례 및 사례 개념화 보고서 저장소. |
| [`maeumnarae/repositories/consultation_repo.py`](../maeumnarae/repositories/consultation_repo.py) | 교사별 자문 일지 저장 및 최신순 조회. |
| [`maeumnarae/repositories/counseling_repo.py`](../maeumnarae/repositories/counseling_repo.py) | 상담 일정/마크다운 일지 CRUD와 타임라인/캘린더용 기간 조회. |
| [`maeumnarae/repositories/deletion_repo.py`](../maeumnarae/repositories/deletion_repo.py) | 명시적으로 확인한 항목과 종속 기록을 한 트랜잭션에서 삭제한다. |
| [`maeumnarae/repositories/education_event_repo.py`](../maeumnarae/repositories/education_event_repo.py) | 교육/행사 기록의 조회와 저장. |
| [`maeumnarae/repositories/group_counseling_repo.py`](../maeumnarae/repositories/group_counseling_repo.py) | 집단 상담과 집단별 일지의 조회 및 저장. |
| [`maeumnarae/repositories/home_repo.py`](../maeumnarae/repositories/home_repo.py) | 위젯 배치와 할 일을 화면 설정 JSON의 widgets 항목에 보관한다. |
| [`maeumnarae/repositories/journal_export_repo.py`](../maeumnarae/repositories/journal_export_repo.py) | 업로드 서식에 필요한 메타데이터만 한 읽기 트랜잭션에서 조회한다. |
| [`maeumnarae/repositories/legacy_import_repo.py`](../maeumnarae/repositories/legacy_import_repo.py) | 기존 XLSB 자료를 한 트랜잭션으로 추가한다. |
| [`maeumnarae/repositories/psychological_test_repo.py`](../maeumnarae/repositories/psychological_test_repo.py) | 학생별 심리검사 일지 저장과 조회. |
| [`maeumnarae/repositories/reporting_repo.py`](../maeumnarae/repositories/reporting_repo.py) | 캘린더 조회와 기간 통계 집계. 목록 페이지 제한 없이 SQL에서 전체 범위를 집계한다. |
| [`maeumnarae/repositories/roster_import_repo.py`](../maeumnarae/repositories/roster_import_repo.py) | 명부 일괄 등록의 기존 자료 중복 검사와 원자적 저장. |
| [`maeumnarae/repositories/school_settings_repo.py`](../maeumnarae/repositories/school_settings_repo.py) | 학교 정보는 현재 암호화 DB에 함께 보관한다. |
| [`maeumnarae/repositories/special_education_repo.py`](../maeumnarae/repositories/special_education_repo.py) | 학생별 특별교육 등록 정보와 일지 저장소. |
| [`maeumnarae/repositories/student_repo.py`](../maeumnarae/repositories/student_repo.py) | 학생 CRUD 및 검색. SQL은 이 모듈 내부에만 위치한다. |
| [`maeumnarae/repositories/teacher_repo.py`](../maeumnarae/repositories/teacher_repo.py) | 자문 대상 교사의 조회와 저장. |
| [`maeumnarae/services/__init__.py`](../maeumnarae/services/__init__.py) | 외부 서비스 연동. |
| [`maeumnarae/services/calendar_holidays.py`](../maeumnarae/services/calendar_holidays.py) | 대한민국 공휴일과 대체공휴일 조회. |
| [`maeumnarae/services/database_maintenance.py`](../maeumnarae/services/database_maintenance.py) | 암호화 스냅샷 백업과 검증·자동 백업을 거치는 DB 복원. |
| [`maeumnarae/services/journal_export.py`](../maeumnarae/services/journal_export.py) | 상담관리 업로드 서식의 16개 열을 채우고 원본 XLSX 부속 요소를 보존한다. |
| [`maeumnarae/services/legacy_import.py`](../maeumnarae/services/legacy_import.py) | 상담기록관리 XLSB의 저장된 셀 값만 읽는다. 매크로/수식은 실행하지 않는다. |
| [`maeumnarae/services/neis.py`](../maeumnarae/services/neis.py) | 나이스 학교기본정보·급식식단정보 API. 인증키와 원문 오류는 로그에 남기지 않는다. |
| [`maeumnarae/services/reporting.py`](../maeumnarae/services/reporting.py) | 한국 날짜 범위와 통계 보고서 직렬화. UI·DB에 의존하지 않는 순수 함수. |
| [`maeumnarae/services/roster_import.py`](../maeumnarae/services/roster_import.py) | 학생·교사 XLSX 서식과 DB 쓰기 없는 행별 입력 검증. |
| [`maeumnarae/services/updates.py`](../maeumnarae/services/updates.py) | 공개 GitHub Releases의 최신 정식 버전 조회. |
| [`maeumnarae/services/weather.py`](../maeumnarae/services/weather.py) | Open-Meteo 지역 검색 및 현재·7일 예보 조회. |
| [`maeumnarae/views/__init__.py`](../maeumnarae/views/__init__.py) | NiceGUI 표현 계층. 데이터 조회/변경은 저장소에 위임한다. |
| [`maeumnarae/views/about_view.py`](../maeumnarae/views/about_view.py) | 프로그램 소개와 프로그램·서드파티 라이선스 표시. |
| [`maeumnarae/views/app_layout.py`](../maeumnarae/views/app_layout.py) | 사이드바와 클라이언트별 화면 전환. 화면 인스턴스를 유지해 검색 상태를 보존한다. |
| [`maeumnarae/views/attachment_view.py`](../maeumnarae/views/attachment_view.py) | 모든 일지가 공유하는 파일 첨부·다운로드·삭제 창. |
| [`maeumnarae/views/auto_lock.py`](../maeumnarae/views/auto_lock.py) | 클라이언트별 미조작 시간 감지와 DB 자동 잠금. |
| [`maeumnarae/views/calendar_view.py`](../maeumnarae/views/calendar_view.py) | 캘린더 목록과 월간/주간 일정 화면. |
| [`maeumnarae/views/consultation_view.py`](../maeumnarae/views/consultation_view.py) | 자문 페이지의 교사 목록, 교사 정보 편집 및 자문 일지 목록 영역. |
| [`maeumnarae/views/counseling_content.py`](../maeumnarae/views/counseling_content.py) | 기존 마크다운과 서식 있는 상담 본문의 표시 변환. |
| [`maeumnarae/views/counseling_view.py`](../maeumnarae/views/counseling_view.py) | 학생별 상담 일지 목록과 서식 편집/미리보기. SQL은 저장소에 위임한다. |
| [`maeumnarae/views/database_settings_view.py`](../maeumnarae/views/database_settings_view.py) | DB 폴더 열기, 암호화 백업 다운로드, 파일 업로드 복원 컨트롤. |
| [`maeumnarae/views/delete_action.py`](../maeumnarae/views/delete_action.py) | 삭제 확인, 중복 실행 방지 및 오류 표시를 공유한다. |
| [`maeumnarae/views/display_settings.py`](../maeumnarae/views/display_settings.py) | DB와 독립적인 기기별 화면 설정 및 테마 적용. |
| [`maeumnarae/views/education_event_view.py`](../maeumnarae/views/education_event_view.py) | 교육/행사 목록과 선택 항목의 상세 내용을 나란히 표시한다. |
| [`maeumnarae/views/group_counseling_view.py`](../maeumnarae/views/group_counseling_view.py) | 집단 목록, 선택 집단의 상세 정보와 회기별 상담일지. |
| [`maeumnarae/views/home_interactions.py`](../maeumnarae/views/home_interactions.py) | 포인터 이동 중 미리 보고, 완료 시 한 번만 배치를 저장한다. |
| [`maeumnarae/views/home_layout.py`](../maeumnarae/views/home_layout.py) | 홈의 24열 정사각형 격자와 기존 배치 변환. |
| [`maeumnarae/views/home_view.py`](../maeumnarae/views/home_view.py) | 세밀한 홈 격자와 위젯 배치 편집. |
| [`maeumnarae/views/journal_export_view.py`](../maeumnarae/views/journal_export_view.py) | 일지 업로드용 XLSX 생성, 누락 항목 확인 및 다운로드. |
| [`maeumnarae/views/journal_pagination.py`](../maeumnarae/views/journal_pagination.py) | 일지 목록의 페이지 크기와 전체 페이지 계산. |
| [`maeumnarae/views/legacy_import_view.py`](../maeumnarae/views/legacy_import_view.py) | XLSB 이관 옵션, 미리보기 및 명시적 저장. |
| [`maeumnarae/views/password_settings_view.py`](../maeumnarae/views/password_settings_view.py) | 현재 DB의 비밀번호 변경 다이얼로그. |
| [`maeumnarae/views/psychological_test_view.py`](../maeumnarae/views/psychological_test_view.py) | 왼쪽 학생 목록과 오른쪽 학생별 심리검사 일지 목록. |
| [`maeumnarae/views/roster_import_view.py`](../maeumnarae/views/roster_import_view.py) | XLSX 명부 서식 다운로드, 업로드 미리보기와 일괄 등록 컨트롤. |
| [`maeumnarae/views/school_settings_view.py`](../maeumnarae/views/school_settings_view.py) | 학교 정보 입력 및 저장 카드의 본문. |
| [`maeumnarae/views/settings_card.py`](../maeumnarae/views/settings_card.py) | 설정 화면에서 사용하는 공통 카드 레이아웃. |
| [`maeumnarae/views/settings_view.py`](../maeumnarae/views/settings_view.py) | 일반, 화면, 시스템, DB, 프로그램 정보 탭으로 구성한 설정 화면. |
| [`maeumnarae/views/special_education_view.py`](../maeumnarae/views/special_education_view.py) | 개인 상담과 같은 학생 선택/일지 흐름을 사용하는 특별교육 화면. |
| [`maeumnarae/views/statistics_view.py`](../maeumnarae/views/statistics_view.py) | 기간별 완료 상담 통계와 집계 보고서 다운로드. |
| [`maeumnarae/views/student_list.py`](../maeumnarae/views/student_list.py) | 다른 화면에서 재사용하는 학생 목록 카드, 검색 및 페이지 이동. |
| [`maeumnarae/views/student_view.py`](../maeumnarae/views/student_view.py) | 학생 목록, 편집 모달, 상세 프로필 및 상담 타임라인. |
| [`maeumnarae/views/time_inputs.py`](../maeumnarae/views/time_inputs.py) | 시간 입력은 오전/오후 12시간제로 표시하고 저장 시 24시간제로 변환한다. |
| [`maeumnarae/views/update_notification.py`](../maeumnarae/views/update_notification.py) | 앱 실행 중 한 번만 업데이트를 확인하고 릴리스 변경사항을 표시한다. |
| [`maeumnarae/widgets/__init__.py`](../maeumnarae/widgets/__init__.py) | 홈 위젯 등록부. 각 위젯의 UI와 동작은 개별 모듈에서 관리한다. |
| [`maeumnarae/widgets/digital_clock.py`](../maeumnarae/widgets/digital_clock.py) | 한국 표준시 디지털 시계 위젯. |
| [`maeumnarae/widgets/meal.py`](../maeumnarae/widgets/meal.py) | 학교 설정을 이용하는 날짜별 나이스 급식 위젯. |
| [`maeumnarae/widgets/memo.py`](../maeumnarae/widgets/memo.py) | 인스턴스별 서식 있는 메모. 변경 즉시 공용 설정 JSON에 저장한다. |
| [`maeumnarae/widgets/teacher_search.py`](../maeumnarae/widgets/teacher_search.py) | 기존 교사 명부를 검색해 연락처와 담당 업무를 확인한다. |
| [`maeumnarae/widgets/todo_list.py`](../maeumnarae/widgets/todo_list.py) | 목록별 할 일과 완료 내역, 기한·우선순위를 관리한다. |
| [`maeumnarae/widgets/weather.py`](../maeumnarae/widgets/weather.py) | 기기 위치 또는 직접 선택한 지역의 일간·주간 날씨. |

## 테스트

| 파일 | 목적·용도 |
| --- | --- |
| [`tests/browser_smoke.py`](../tests/browser_smoke.py) | 실행 중인 로컬 앱을 Chrome 임시 프로필로 검사한다. 테스트 DB에만 사용한다. |
| [`tests/test_app_layout.py`](../tests/test_app_layout.py) | 학생 변경을 이미 생성된 모든 화면에 반영한다. |
| [`tests/test_attachments.py`](../tests/test_attachments.py) | 첨부파일 격리·암호화·연쇄 삭제 및 실제 UI 업로드 흐름 검증. |
| [`tests/test_authors.py`](../tests/test_authors.py) | 실제 SQLCipher에서 작성자 스냅샷, 수정 및 구버전 마이그레이션 검증. |
| [`tests/test_auto_lock.py`](../tests/test_auto_lock.py) | 자동 잠금의 만료 경계, 입력 갱신, 저장 및 화면 연결 검사. |
| [`tests/test_calendar_view.py`](../tests/test_calendar_view.py) | 캘린더 저장, 선택 필터 및 월간/주간 탐색 검증. |
| [`tests/test_connection_guards.py`](../tests/test_connection_guards.py) | 외부 패키지 없이 평문 드라이버 거부와 경로 처리 계약을 검사한다. |
| [`tests/test_consultation.py`](../tests/test_consultation.py) | 자문 일지 저장 격리와 에디터 저장/재시도 검증. |
| [`tests/test_counseling_content.py`](../tests/test_counseling_content.py) | 테스트: counseling content |
| [`tests/test_counseling_view.py`](../tests/test_counseling_view.py) | 상담 폼 변환, 목록 격리, 조회 실패를 검증한다. |
| [`tests/test_database_maintenance.py`](../tests/test_database_maintenance.py) | 실제 SQLCipher 파일의 백업·검증·원자적 복원과 실패 시 원본 보존. |
| [`tests/test_database_settings_view.py`](../tests/test_database_settings_view.py) | DB 탭에서 백업 다운로드와 파일 업로드 복원 흐름을 검사한다. |
| [`tests/test_delete_action.py`](../tests/test_delete_action.py) | 실제 UI 확인창의 취소·확인 및 오류 후 재시도를 검증한다. |
| [`tests/test_deletion.py`](../tests/test_deletion.py) | 실제 암호화 DB에서 삭제 범위와 트랜잭션의 원자성을 검증한다. |
| [`tests/test_display_settings.py`](../tests/test_display_settings.py) | 화면 설정 복원, 잘못된 값 방어 및 네이티브 아이콘 전달 검사. |
| [`tests/test_education_events.py`](../tests/test_education_events.py) | 교육/행사 저장과 목록 선택 검증. |
| [`tests/test_group_counseling.py`](../tests/test_group_counseling.py) | 집단별 저장 격리, 선택 응답 순서와 화면 구성을 검증한다. |
| [`tests/test_home_widgets.py`](../tests/test_home_widgets.py) | 홈 저장소의 지속성, 마이그레이션, 검색 범위와 배치 실패 복원 검증. |
| [`tests/test_journal_export.py`](../tests/test_journal_export.py) | 업로드 서식, 전체 일지 조회, 한국 학년도 경계와 비공개 내용 제외 검증. |
| [`tests/test_journal_pagination.py`](../tests/test_journal_pagination.py) | 일지 페이지 경계와 저장소별 전체 건수 조회 검증. |
| [`tests/test_legacy_import.py`](../tests/test_legacy_import.py) | 익명 데이터와 임시 암호화 DB로 이관/재등록/롤백을 검증한다. |
| [`tests/test_legacy_import_view.py`](../tests/test_legacy_import_view.py) | 테스트: legacy import view |
| [`tests/test_meal_widget.py`](../tests/test_meal_widget.py) | 나이스 요청·오류·구버전 학교 설정·급식 위젯 날짜 전환 검증. |
| [`tests/test_memo_widget.py`](../tests/test_memo_widget.py) | 메모의 서식·인스턴스 분리·저장 실패 복구 검증. |
| [`tests/test_password_settings.py`](../tests/test_password_settings.py) | 실제 SQLCipher 키 변경과 변경 폼의 검증·중복 실행 방지. |
| [`tests/test_program_info.py`](../tests/test_program_info.py) | 프로그램 라이선스 전문과 추가 라이선스 자료의 로딩을 검증한다. |
| [`tests/test_psychological_tests.py`](../tests/test_psychological_tests.py) | 심리검사 일지의 학생별 격리와 화면 선택 검증. |
| [`tests/test_reporting.py`](../tests/test_reporting.py) | 실제 SQLCipher 집계, 한국 날짜 경계, 보고서 일관성과 달력 계산 검증. |
| [`tests/test_repositories.py`](../tests/test_repositories.py) | 실제 SQLCipher로만 수행하는 통합 테스트. 가짜/평문 DB로 대체하지 않는다. |
| [`tests/test_rich_content.py`](../tests/test_rich_content.py) | 일반 텍스트 호환 및 내용 서식 보존. |
| [`tests/test_roster_import.py`](../tests/test_roster_import.py) | 실제 XLSX와 SQLCipher로 명부 검증, 전체 롤백, 작성자와 저장 필드 확인. |
| [`tests/test_roster_import_view.py`](../tests/test_roster_import_view.py) | DB 탭에서 서식 다운로드, 오류 차단, 명부 등록 및 새로고침 흐름 검증. |
| [`tests/test_school_settings.py`](../tests/test_school_settings.py) | 암호화 DB의 학교 정보 저장, 복원 및 이전 버전 업그레이드. |
| [`tests/test_special_education.py`](../tests/test_special_education.py) | 특별교육 등록 항목과 학생/교육별 저장 격리 검증. |
| [`tests/test_student_enrollments.py`](../tests/test_student_enrollments.py) | 학년도 누적, 최신 학적 선택, 충돌 롤백 및 구버전 DB 이관. |
| [`tests/test_student_list.py`](../tests/test_student_list.py) | 독립 목록 인스턴스와 동기/비동기 선택 콜백을 검사한다. |
| [`tests/test_student_view.py`](../tests/test_student_view.py) | 실제 NiceGUI 요소와 가짜 저장소로 화면 상태 및 비동기 경쟁을 검사한다. |
| [`tests/test_teachers.py`](../tests/test_teachers.py) | 교사 저장, 기존 DB 마이그레이션 및 자문 목록 검증. |
| [`tests/test_time_inputs.py`](../tests/test_time_inputs.py) | 12시간제 입력의 자정·정오 변환 및 저장 형식 검증. |
| [`tests/test_updates.py`](../tests/test_updates.py) | 업데이트 버전 비교, 네트워크 실패, 시작 시 중복 확인 및 알림 UI 검증. |
| [`tests/test_weather_widget.py`](../tests/test_weather_widget.py) | 테스트: weather widget |

## 의존성·빌드·문서

| 파일 | 목적·용도 |
| --- | --- |
| [`docs/building.md`](../docs/building.md) | 실행·OS별 빌드·업데이트 배포 절차. |
| [`docs/project-structure.md`](project-structure.md) | 폴더별 역할, 전체 파일 용도와 이동 경로 안내. |
| [`docs/legacy-import.md`](../docs/legacy-import.md) | 기존 프로그램 자료 이관 형식과 절차. |
| [`packaging/maeumnarae-data.spec`](../packaging/maeumnarae-data.spec) | DB 초기화 콘솔 도구 번들 구성. |
| [`packaging/maeumnarae.spec`](../packaging/maeumnarae.spec) | 전체 데스크톱 앱 번들 구성과 플랫폼별 의존성. |
| [`requirements/base.txt`](../requirements/base.txt) | 앱 공통 런타임 의존성. |
| [`requirements/build.txt`](../requirements/build.txt) | 데스크톱 의존성과 배포·이미지 빌드 도구. |
| [`requirements/desktop.txt`](../requirements/desktop.txt) | 공통 의존성과 네이티브 웹뷰. |
| [`requirements/dev.txt`](../requirements/dev.txt) | 공통 의존성과 테스트·개발 도구. |
| [`scripts/build_desktop.py`](../scripts/build_desktop.py) | 현재 OS/CPU의 독립 실행 앱을 빌드한다: python scripts/build_desktop.py. |

## 배포 리소스

| 파일 | 목적·용도 |
| --- | --- |
| [`resources/fonts/NotoSansKR-VariableFont_wght.ttf`](../resources/fonts/NotoSansKR-VariableFont_wght.ttf) | 앱 화면에 선택 적용하는 번들 글꼴. |
| [`resources/fonts/PretendardVariable.ttf`](../resources/fonts/PretendardVariable.ttf) | 앱 화면에 선택 적용하는 번들 글꼴. |
| [`resources/icons/icon-dark.ico`](../resources/icons/icon-dark.ico) | 어두운 테마용 앱 아이콘. |
| [`resources/icons/icon-dark.png`](../resources/icons/icon-dark.png) | 어두운 테마용 앱 아이콘. |
| [`resources/icons/icon.ico`](../resources/icons/icon.ico) | 기본 앱 아이콘. |
| [`resources/licenses/README.md`](../resources/licenses/README.md) | 라이선스 원문 출처와 갱신 방법. |
| [`resources/licenses/fonts/noto.txt`](../resources/licenses/fonts/noto.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/fonts/pretendard.txt`](../resources/licenses/fonts/pretendard.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/certifi.txt`](../resources/licenses/libraries/certifi.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/defusedxml.txt`](../resources/licenses/libraries/defusedxml.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/et_xmlfile.txt`](../resources/licenses/libraries/et_xmlfile.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/holidays.txt`](../resources/licenses/libraries/holidays.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/markdown2.txt`](../resources/licenses/libraries/markdown2.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/nh3.txt`](../resources/licenses/libraries/nh3.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/nicegui.txt`](../resources/licenses/libraries/nicegui.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/openpyxl.txt`](../resources/licenses/libraries/openpyxl.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/pydantic.txt`](../resources/licenses/libraries/pydantic.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/pywebview.txt`](../resources/licenses/libraries/pywebview.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/pyxlsb.txt`](../resources/licenses/libraries/pyxlsb.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/libraries/sqlcipher3.txt`](../resources/licenses/libraries/sqlcipher3.txt) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/manifest.json`](../resources/licenses/manifest.json) | 프로그램 정보 탭의 라이선스 종류·원문·출처 목록. |
| [`resources/licenses/pyxlsb/COPYING`](../resources/licenses/pyxlsb/COPYING) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/licenses/pyxlsb/COPYING.LESSER`](../resources/licenses/pyxlsb/COPYING.LESSER) | 라이선스·저작권 고지 원문 (프로그램 정보 탭에서 표시). |
| [`resources/templates/counseling_upload.xlsx`](../resources/templates/counseling_upload.xlsx) | 상담 실적 엑셀 내보내기 기준 서식. |

## 검증 및 디자인 자료

| 파일 | 목적·용도 |
| --- | --- |
| [`artifacts/design/icon-dark-flat-prompt.txt`](../artifacts/design/icon-dark-flat-prompt.txt) | 아이콘 제작 프롬프트 기록. |
| [`artifacts/design/icon-dark-prompt.txt`](../artifacts/design/icon-dark-prompt.txt) | 아이콘 제작 프롬프트 기록. |
| [`artifacts/logs/build-desktop.log`](../artifacts/logs/build-desktop.log) | 기존 빌드·네이티브 실행 검증 로그. |
| [`artifacts/logs/packaged-native.log`](../artifacts/logs/packaged-native.log) | 기존 빌드·네이티브 실행 검증 로그. |
| [`artifacts/reports/native-report.csv`](../artifacts/reports/native-report.csv) | 보고서 내보내기 검증 결과. |
| [`artifacts/screenshots/calendar.png`](../artifacts/screenshots/calendar.png) | 기능 화면 검증 캡처. |
| [`artifacts/screenshots/counseling-editor.png`](../artifacts/screenshots/counseling-editor.png) | 기능 화면 검증 캡처. |
| [`artifacts/screenshots/home.png`](../artifacts/screenshots/home.png) | 기능 화면 검증 캡처. |
| [`artifacts/screenshots/statistics.png`](../artifacts/screenshots/statistics.png) | 기능 화면 검증 캡처. |
| [`artifacts/screenshots/student.png`](../artifacts/screenshots/student.png) | 기능 화면 검증 캡처. |

## 주요 이동 경로

| 이전 | 현재 |
| --- | --- |
| `database.py` | `maeumnarae/core/database.py` |
| `models.py` | `maeumnarae/core/models.py` |
| `settings_store.py` | `maeumnarae/core/settings_store.py` |
| `program_info.py` | `maeumnarae/core/program_info.py` |
| `desktop.py` | `maeumnarae/core/desktop.py` |
| `app_fonts.py` | `maeumnarae/core/app_fonts.py` |
| `reporting.py` | `maeumnarae/services/reporting.py` |
| `calendar_holidays.py` | `maeumnarae/services/calendar_holidays.py` |
| `home_layout.py` | `maeumnarae/views/home_layout.py` |
| `main.py` | `maeumnarae/application.py` |
| `init_db.py` | `maeumnarae/cli.py` |
| `BUILDING.md` | `docs/building.md` |
| `maeumnarae.spec` | `packaging/maeumnarae.spec` |
| `maeumnarae-data.spec` | `packaging/maeumnarae-data.spec` |
| `requirements.txt` | `requirements/base.txt` |
| `requirements-dev.txt` | `requirements/dev.txt` |
| `requirements-desktop.txt` | `requirements/desktop.txt` |
| `requirements-build.txt` | `requirements/build.txt` |
| `fonts/NotoSansKR-VariableFont_wght.ttf` | `resources/fonts/NotoSansKR-VariableFont_wght.ttf` |
| `fonts/PretendardVariable.ttf` | `resources/fonts/PretendardVariable.ttf` |
| `licenses/README.md` | `resources/licenses/README.md` |
| `licenses/manifest.json` | `resources/licenses/manifest.json` |
| `icon.ico` | `resources/icons/icon.ico` |
| `icon-dark.ico` | `resources/icons/icon-dark.ico` |
| `icon-dark.png` | `resources/icons/icon-dark.png` |

기존 `repositories/`, `services/`, `views/`, `widgets/`는 `maeumnarae/` 아래로 이동했습니다.
기존 `licenses/`는 `resources/licenses/`로 이동했습니다. 파일별 내용은 보존했습니다.
