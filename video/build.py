"""把 config.json 注入版式模板，生成 video/slides.html 与采集清单。

用法： python video/build.py
产物：
  video/slides.html          可直接被 Chrome 打开渲染（相对路径引用 assets/）
  video/build/pages.txt      页面 id（每行一个，含 cover）
  video/build/subs.txt       字幕层 id
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
CFG_PATH = ROOT / "config.json"
TPL_PATH = ROOT / "slides.tpl.html"
OUT_HTML = ROOT / "slides.html"
BUILD = ROOT / "build"

PAGE_IDS = [
    "s01a", "s01b", "s02", "s03a", "s03b",
    "s04a", "s04b", "s04c", "s04d",
    "s05a", "s05b", "s05c", "s05d",
    "s06a", "s06b", "s06c", "s06d", "s06e", "s06f",
    "s07a", "s07b", "s07c", "s07d",
    "s08a",
    "s10a",
    "cover",
]

OVERLAY_IDS = ["o02", "o04a", "o04b", "o04c", "o04d", "o05",
               "o08a", "o08b", "o08c", "o08d"]


CAPTION_IDS: list[str] = []


def build_captions(cfg: dict) -> dict:
    """每条旁白句子 → 一句字幕（抖音式逐句）。"""
    caps = {}
    n = 0
    for shot in cfg["shots"]:
        parts = [x.strip("，, 。.！!？?；; ") for x in shot["narration"].split("／")
                 if x.strip("，, 。.！!？?；; ")]
        for part in parts:
            n += 1
            cid = f"c{n:03d}"
            caps[cid] = part
            CAPTION_IDS.append(cid)
    return caps


def make_crops() -> None:
    """把站点全景裁成以图形为中心的方图，避免版式页里大片空天。"""
    from PIL import Image

    src = ROOT / "assets" / "a1.png"
    if not src.exists():
        print("[skip] assets/a1.png not captured yet")
        return
    im = Image.open(src)
    w, h = im.size
    side = int(min(w, h) * 0.787)          # 1700 / 2160
    cx, cy = int(w * 0.5), int(h * 0.648)  # 图形视觉中心
    left = max(0, min(w - side, cx - side // 2))
    top = max(0, min(h - side, cy - side // 2))
    im.crop((left, top, left + side, top + side)).save(ROOT / "assets" / "a1c.png")
    print(f"a1c.png  <- a1 crop {side}x{side} at ({left},{top})")


def main() -> int:
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    tpl = TPL_PATH.read_text(encoding="utf-8")
    if "__CFG__" not in tpl:
        print("template missing __CFG__ placeholder", file=sys.stderr)
        return 1
    caps = build_captions(cfg)
    payload = json.dumps(cfg, ensure_ascii=False, separators=(",", ":"))
    html = tpl.replace("__CFG__", payload).replace("__CAPS__", json.dumps(caps, ensure_ascii=False))
    OUT_HTML.write_text(html, encoding="utf-8")

    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "pages.txt").write_text("\n".join(PAGE_IDS) + "\n", encoding="utf-8")
    subs = [f"sub{i:02d}" for i in range(1, len(cfg["shots"]) + 1)]
    (BUILD / "subs.txt").write_text("\n".join(subs) + "\n", encoding="utf-8")
    (BUILD / "overlays.txt").write_text("\n".join(OVERLAY_IDS) + "\n", encoding="utf-8")
    (BUILD / "captions.txt").write_text("\n".join(CAPTION_IDS) + "\n", encoding="utf-8")
    (BUILD / "captions.json").write_text(json.dumps(caps, ensure_ascii=False, indent=1), encoding="utf-8")

    total = len(PAGE_IDS) + len(subs) + len(OVERLAY_IDS) + len(CAPTION_IDS)
    make_crops()
    print(f"slides.html  -> {OUT_HTML}")
    print(f"pages={len(PAGE_IDS)}  subs={len(subs)}  overlays={len(OVERLAY_IDS)}"
          f"  captions={len(CAPTION_IDS)}  total={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
