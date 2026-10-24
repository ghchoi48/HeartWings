"""소스 실행과 PyInstaller 번들에서 동일하게 쓰는 읽기 전용 리소스 경로."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESOURCE_ROOT = PROJECT_ROOT / 'resources'
