# 마음나래 앱 아이콘

Apple [App icons HIG](https://developer.apple.com/design/human-interface-guidelines/app-icons)의
단순한 형태, 중앙 배치, 작은 크기에서의 식별성 원칙을 참고했다.
기존 사람·하트·날개와 금색 정체성을 유지하고 배경 제거 잡티를 정리했다.

- `icon.png`, `icon-dark.png`: 불투명 정사각형 원본, 기본/다크 테마.
- `icon.ico`, `icon-dark.ico`: Windows와 브라우저용 16–256px 이미지.
- `icon.icns`, `icon-dark.icns`: macOS 번들 및 실행 중 Dock 아이콘.
- `icon-desktop.png`, `icon-dark-desktop.png`: 둥근 모서리와 투명 여백이 적용된 1024px 배포 이미지 및 Linux 창 아이콘.
- `logo.png`, `logo-dark.png`: 앱 화면 내부 전용 배경 투명 로고.

원본은 모서리를 미리 자르지 않은 평면 이미지다. 생성 스크립트는 Windows ICO와
macOS ICNS 모두에 약 9.8%의 바깥쪽 투명 여백과 둥근 모서리를 직접 적용한다.
실행 중 Dock 아이콘 API가 자동으로 모서리를 잘라주지 않으므로 출력 파일에
알파 마스크를 포함한다. 화면 내부 로고는 별도 투명 PNG를 사용한다.
현재 PyInstaller의 기존 ICNS
파이프라인을 사용하며 Icon Composer의 레이어, 시스템별 clear/tinted 변형 및
동적 Liquid Glass 처리는 구현하지 않는다. Apple의 전체 최신 아이콘 파이프라인을
지원한다는 의미는 아니다. 기존 dist 앱에는 재빌드 후 반영된다.

재생성 (Pillow는 requirements/build.txt에 포함):

```sh
python scripts/build_icons.py
```

이미지는 내장 image_gen 도구로 수정했다. 최종 프롬프트:

> Use case: style-transfer. Edit target: supplied HeartWings app icon. Create a production square 1024x1024 app icon master following Apple HIG simplicity and centered composition. Preserve recognizable person with circular head, heart at chest, and symmetric embracing wings, but redraw as clean bold smooth geometry with fewer feather details, no distressed specks. Keep warm gold identity: rich dark golden ochre emblem on a uniform warm ivory background. Emblem occupies centered 68 percent of canvas width and height, with ample safe area. Solid opaque full bleed square background, NO rounded outer corners, NO frame, NO shadows, NO glass effects, NO text, NO Apple logos, NO mockup. Flat high contrast elegant graphic, thick strokes that remain readable at 32px. Save output image.

다크 변형 프롬프트:

> Use case: style-transfer. Edit target: this app icon. Create its dark appearance variant. Preserve exactly all emblem geometry, position, scale and stroke weights: winged person with heart. Change ONLY colors: background to solid deep charcoal #202124, emblem to light warm gold #F4D985. Square full bleed opaque background. No rounded outer corners, no shadow, no new elements, no text. Clean smooth edges, no specks.

앱 내부 로고의 배경 제거에는 내장 image_gen을 사용했다. 기본/다크 프롬프트는
각각 ivory/gold와 charcoal/light gold를 사용한다:

> Background extraction only. Remove all ivory background from this gold winged-person-and-heart logo, including enclosed spaces within head, heart, wings, circle. Genuine transparent alpha background. Preserve exact golden emblem shape, color, placement and proportions. No redesign, no new elements, no shadow. Square canvas.

> Background extraction only. Remove all charcoal background from this light gold winged-person-and-heart logo, including enclosed spaces within head, heart, wings, circle. Genuine transparent alpha background. Preserve exact light gold emblem shape, color, placement and proportions. No redesign, no new elements, no shadow. Square canvas.
