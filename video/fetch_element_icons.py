"""从 biligame 元素页抓 7 个官方元素图标原图（卡牌UI-元素-*.png）。

用法： python video/fetch_element_icons.py
产物： video/assets/el/{fire,water,thunder,ice,anemo,geo,grass}.png
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "assets" / "el"
PAGE = "https://wiki.biligame.com/ys/%E5%85%83%E7%B4%A0"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
MAP = {"火": "fire", "水": "water", "雷": "thunder", "冰": "ice",
       "风": "anemo", "岩": "geo", "草": "grass"}

THUMB = re.compile(
    r"https://patchwiki\.biligame\.com/images/ys/thumb/(\d)/([0-9a-f]{2})/([0-9a-z]+)\.png/\d+px-([^\"'<> ]+?\.png)",
    re.I,
)
DIRECT = re.compile(
    r"https://patchwiki\.biligame\.com/images/ys/(\d)/([0-9a-f]{2})/([0-9a-z]+)\.png",
    re.I,
)


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://wiki.biligame.com/ys/"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    html = get(PAGE).decode("utf-8", "replace")

    want: dict[str, str] = {}          # 元素中文 → 原图 url
    for m in THUMB.finditer(html):
        name = urllib.parse.unquote(m.group(4))
        elem = name.replace("卡牌UI-元素-", "").replace(".png", "")
        if elem in MAP and elem not in want:
            want[elem] = f"https://patchwiki.biligame.com/images/ys/{m.group(1)}/{m.group(2)}/{m.group(3)}.png"
    for m in DIRECT.finditer(html):
        blob = m.group(0)
        # 直链没有文件名，靠上下文判定：位置附近的 alt/aria-label 不好拿，跳过
        _ = blob

    missing = [e for e in MAP if e not in want]
    print("found:", {k: MAP[k] for k in want}, "missing:", missing)

    for elem, url in want.items():
        dst = OUT / f"{MAP[elem]}.png"
        dst.write_bytes(get(url))
        print(f"  {elem} -> {dst}  {dst.stat().st_size} bytes")

    # 缺的再单独兜底：直接猜 file 路径（wiki 原图命名固定）
    for elem in missing:
        key = MAP[elem]
        alt = f"https://patchwiki.biligame.com/images/ys/{urllib.parse.quote(elem)}.png"
        try:
            OUT.joinpath(f"{key}.png").write_bytes(get(alt))
            print(f"  fallback {elem} -> {alt}")
        except Exception as e:  # noqa: BLE001
            print(f"  still missing {elem}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
