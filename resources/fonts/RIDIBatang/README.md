# 리디바탕 PDF 글꼴

기본 PDF 서체로 사용하는 리디바탕의 TrueType 변환본입니다.
공식 OTF의 CFF 윤곽선을 ReportLab이 지원하는 quadratic TrueType 윤곽선으로 변환했습니다.
글꼴 이름은 `HeartWings Ridi Batang`으로 변경했으며 원 저작권 정보를 보존합니다.
원본은 Regular만 제공하므로 PDF의 굵은 강조에는 기존 JournalSans Bold를 사용합니다.

- 공식 안내: https://ridicorp.com/ridibatang/
- 원본: https://ridicorp.com/wp-content/themes/ridicorp/css/font/RIDIBatang.otf
- 라이선스: ../../licenses/fonts/ridibatang.txt (SIL OFL 1.1)
- 변환 도구: fontTools 4.67.0, 최대 윤곽선 오차 1 font unit

원본을 다운로드하고 개발 환경에 fontTools를 설치한 뒤 프로젝트 루트에서 실행합니다.

```sh
python scripts/convert_ridibatang.py /path/to/RIDIBatang.otf resources/fonts/RIDIBatang/HeartWingsRidiBatang-Regular.ttf
```

배포 앱 실행 시 fontTools나 네트워크 연결은 필요하지 않습니다.
