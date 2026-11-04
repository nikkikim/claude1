"""archive/*.json(하루 한 개씩 보관된 브리핑)로 웹사이트(_site/)를 만든다. GitHub Pages로 배포된다.

    python build_site.py [보관폴더=archive] [출력폴더=_site]

- index.html : 가장 최근 브리핑 + 지난 브리핑 목록
- YYYY-MM-DD.html : 날짜별 브리핑(이전/다음 날 링크)
- archive.html : 전체 목록
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path

import news_digest as nd

CSS = """
:root{color-scheme:light}
body{margin:0;background:#f6f7f9;color:#222;font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif}
main{max-width:680px;margin:0 auto;padding:20px 16px 48px;background:#fff;min-height:100vh}
nav{display:flex;justify-content:space-between;gap:8px;font-size:14px;margin:0 0 16px}
nav a{color:#0b57d0;text-decoration:none}
nav .off{color:#bbb}
.past{margin-top:32px;border-top:1px solid #ddd;padding-top:12px;font-size:14px}
.past h2{font-size:15px;margin:0 0 8px}
.past li{margin:4px 0}
.past a{color:#0b57d0;text-decoration:none}
.past span{color:#777}
"""


def _page(title: str, body: str) -> str:
    e = html.escape
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow">'
            f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>")


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


def _list_html(items: list[tuple[str, dict]], limit: int | None = None) -> str:
    e = html.escape
    rows = "".join(f'<li><a href="{d}.html">{d}</a> <span>{e(str(g.get("headline", ""))[:80])}</span></li>'
                   for d, g in items[:limit])
    return f"<ul>{rows}</ul>"


def build(src: Path, out: Path) -> int:
    items = load_archive(src)
    out.mkdir(parents=True, exist_ok=True)
    if not items:
        (out / "index.html").write_text(_page("뉴스 브리핑", "<p>아직 보관된 브리핑이 없습니다. 내일 아침에 첫 브리핑이 올라옵니다.</p>"), encoding="utf-8")
        return 0
    for i, (day, digest) in enumerate(items):
        newer = items[i - 1][0] if i > 0 else None
        older = items[i + 1][0] if i + 1 < len(items) else None
        nav = ('<nav>' + (f'<a href="{older}.html">← {older}</a>' if older else '<span class="off">←</span>')
               + '<a href="archive.html">전체 목록</a>'
               + (f'<a href="{newer}.html">{newer} →</a>' if newer else '<span class="off">→</span>') + '</nav>')
        date = datetime.strptime(day, "%Y-%m-%d")
        body = nav + nd.render_html(digest, date)
        page = _page(f"{day} 뉴스 브리핑", body)
        (out / f"{day}.html").write_text(page, encoding="utf-8")
        if i == 0:  # 가장 최근 브리핑 + 지난 목록
            past = '<div class="past"><h2>지난 브리핑</h2>' + _list_html(items[1:], 30) + "</div>" if len(items) > 1 else ""
            (out / "index.html").write_text(_page("뉴스 브리핑", body + past), encoding="utf-8")
    (out / "archive.html").write_text(
        _page("전체 브리핑 목록", f'<nav><a href="index.html">← 최신 브리핑</a></nav><h1 style="font-size:20px">전체 브리핑 ({len(items)}개)</h1>'
              + _list_html(items)), encoding="utf-8")
    return len(items)


if __name__ == "__main__":
    n = build(Path(sys.argv[1] if len(sys.argv) > 1 else "archive"), Path(sys.argv[2] if len(sys.argv) > 2 else "_site"))
    print(f"웹사이트 생성 완료: 브리핑 {n}개")
