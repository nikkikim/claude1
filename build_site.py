"""archive/*.json(하루 한 개씩 보관된 브리핑)로 웹사이트(_site/)를 만든다. GitHub Pages로 배포된다.

    python build_site.py [보관폴더=archive] [출력폴더=_site]

만들어지는 것:
- _site/index.html, style.css, app.js : site/ 폴더의 화면 파일(달력·날짜별 보기·이메일 보내기 버튼)
- _site/config.js                     : 저장소 이름·브랜치(이메일 보내기 버튼이 사용)
- _site/data/index.json               : [{"d": 날짜, "h": 한 줄 요약}] 최신순 (달력에 표시)
- _site/data/YYYY-MM-DD.json          : 그날의 브리핑 본문(브라우저가 필요할 때 불러옴)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

SITE_SRC = Path(__file__).with_name("site")
ASSETS = ("index.html", "style.css", "app.js")


def load_archive(src: Path) -> list[tuple[str, dict]]:
    """[(날짜 'YYYY-MM-DD', digest)] 최신순. 읽을 수 없는 파일은 건너뛴다."""
    items = []
    for f in sorted(src.glob("*.json"), reverse=True):
        try:
            datetime.strptime(f.stem, "%Y-%m-%d")
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                items.append((f.stem, data))
        except (ValueError, OSError):
            print(f"[warn] 보관 파일을 건너뜁니다: {f.name}", file=sys.stderr)
    return items


def _js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def build(src: Path, out: Path) -> int:
    items = load_archive(src)
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    for name in ASSETS:
        shutil.copy(SITE_SRC / name, out / name)
    (out / "config.js").write_text(
        "window.SITE_CONFIG={repo:%s,workflow:%s,ref:%s};\n" % (
            _js_string(os.environ.get("GITHUB_REPOSITORY", "")), _js_string("daily-news.yml"),
            _js_string(os.environ.get("GITHUB_REF_NAME", "main"))), encoding="utf-8")
    index = []
    for day, digest in items:
        (out / "data" / f"{day}.json").write_text(
            json.dumps(digest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append({"d": day, "h": str(digest.get("headline", ""))[:120]})
    (out / "data" / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(items)


if __name__ == "__main__":
    n = build(Path(sys.argv[1] if len(sys.argv) > 1 else "archive"), Path(sys.argv[2] if len(sys.argv) > 2 else "_site"))
    print(f"웹사이트 생성 완료: 브리핑 {n}개")
