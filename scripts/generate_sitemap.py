
"""GitHub Pages용 sitemap.xml 자동 생성."""

from datetime import date
from pathlib import Path
from urllib.parse import quote
import subprocess
import xml.etree.ElementTree as ET

# 프로젝트 루트
ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / "website"

# GitHub Pages 기본 주소
BASE_URL = "https://ghchoi48.github.io/HeartWings/"

# 사이트맵에서 제외할 파일
EXCLUDED_FILES = {"404.html"}
EXCLUDED_DIRS = {"assets", "node_modules", "dist"}

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
ET.register_namespace("", NS)


def should_include(path: Path) -> bool:
    """검색엔진에 등록할 HTML만 선택한다."""
    relative = path.relative_to(WEBSITE)

    if any(part in EXCLUDED_DIRS for part in relative.parts[:-1]):
        return False

    if path.name in EXCLUDED_FILES:
        return False

    # Google 소유권 확인용 HTML 제외
    if path.name.startswith("google"):
        return False

    return True


def get_page_url(path: Path) -> str:
    """HTML 경로를 공개 URL로 변환한다."""
    relative = path.relative_to(WEBSITE)

    # index.html -> 디렉터리 URL
    if path.name == "index.html":
        parent = relative.parent

        if parent == Path("."):
            return BASE_URL

        return BASE_URL + quote(parent.as_posix(), safe="/") + "/"

    return BASE_URL + quote(relative.as_posix(), safe="/")


def get_last_modified(path: Path) -> str | None:
    """Git 기록에서 해당 파일의 최근 커밋 날짜를 가져온다."""
    relative = path.relative_to(ROOT).as_posix()

    result = subprocess.run(
        [
            "git", "log", "-1",
            "--format=%cs",
            "--", relative,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    value = result.stdout.strip()

    if not value:
        return None

    try:
        date.fromisoformat(value)
        return value
    except ValueError:
        return None


def generate_sitemap() -> None:
    if not WEBSITE.is_dir():
        raise FileNotFoundError(f"Website not found: {WEBSITE}")

    pages = sorted(
        (
            p for p in WEBSITE.rglob("*.html")
            if p.is_file() and should_include(p)
        ),
        key=get_page_url,
    )

    if not (WEBSITE / "index.html").is_file():
        raise FileNotFoundError("website/index.html is missing")

    urlset = ET.Element(f"{{{NS}}}urlset")

    for page in pages:
        url = ET.SubElement(urlset, f"{{{NS}}}url")

        loc = ET.SubElement(url, f"{{{NS}}}loc")
        loc.text = get_page_url(page)

        modified = get_last_modified(page)

        if modified:
            lastmod = ET.SubElement(
                url, f"{{{NS}}}lastmod"
            )
            lastmod.text = modified

        print(f"Added: {loc.text}")

    tree = ET.ElementTree(urlset)
    ET.indent(tree, space="  ")

    output = WEBSITE / "sitemap.xml"

    tree.write(
        output,
        encoding="utf-8",
        xml_declaration=True,
    )

    print(f"Generated {output} with {len(pages)} URLs")


if __name__ == "__main__":
    generate_sitemap()
