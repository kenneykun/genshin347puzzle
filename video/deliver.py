"""交付物：封面 + 分镜 PDF（直接取成片里的帧，保证与片内一致）。

用法： python video/deliver.py
产物：
  video/out/cover_1080x1920.png
  video/out/storyboard.pdf
"""
from __future__ import annotations

import json
import pathlib
import subprocess

from PIL import Image

import timeline as tl_mod

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"
OUT = ROOT / "out"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
MP4 = OUT / "three_domain_1080x1920.mp4"


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    cover = Image.open(BUILD / "pages" / "cover.png").convert("RGB")
    cover.resize((1080, 1920), Image.LANCZOS).save(OUT / "cover_1080x1920.png")
    print("cover ->", OUT / "cover_1080x1920.png")

    if not MP4.exists():
        print("[skip] storyboard needs", MP4)
        return 0

    tl = tl_mod.build(CFG)
    story_dir = BUILD / "story"
    story_dir.mkdir(parents=True, exist_ok=True)

    pages = []
    for shot in tl["shots"]:
        t = (shot["start_frame"] + shot["frames"] * 0.55) / tl["fps"]
        png = story_dir / f"shot{shot['id']}.png"
        subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-ss", f"{t:.3f}",
                        "-i", str(MP4), "-frames:v", "1", str(png)], check=True)
        pages.append(Image.open(png).convert("RGB"))
        print(f"  shot {shot['id']} @ {t:5.2f}s")

    pages[0].save(OUT / "storyboard.pdf", save_all=True, append_images=pages[1:],
                  resolution=96.0, quality=92)
    print("storyboard ->", OUT / "storyboard.pdf", f"({len(pages)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
