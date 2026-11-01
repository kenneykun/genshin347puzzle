"""逐帧合成 9 镜 → 1080x1920 / 30fps H.264 成片。

底片来源有两种：版式页 PNG（静态）或 3D 帧序列 build/clips/<name>/fNNNN.jpg（动态）。
动态镜头的文字放在透明覆盖层 build/overlays/<id>.png 里，叠在底片之上。

用法：
  python video/render.py --stills 0,2,5,9.5      # 只出几张检查图到 build/check/
  python video/render.py --video                 # 全片编码到 out/
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import pathlib
import subprocess
import sys
import time

from PIL import Image

import timeline as tl_mod

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"
OUT = ROOT / "out"
CLIPS = BUILD / "clips"

W, H = 1080, 1920
SRCW, SRCH = 2160, 3840
FPS = 30

CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SYS_SHOTS = {s["id"]: s for s in CFG["shots"]}
CFG["shots_by_id"] = SYS_SHOTS

_page_cache: collections.OrderedDict = collections.OrderedDict()
_overlay_cache: dict[str, Image.Image] = {}
_clip_files: dict[str, list[pathlib.Path]] = {}
_clip_cache: collections.OrderedDict = collections.OrderedDict()


def page_img(pid: str) -> Image.Image:
    if pid in _page_cache:
        _page_cache.move_to_end(pid)
        return _page_cache[pid]
    p = BUILD / "pages" / f"{pid}.png"
    if not p.exists():
        raise SystemExit(f"missing page {p}")
    im = Image.open(p).convert("RGB")
    if im.size != (SRCW, SRCH):
        im = im.resize((SRCW, SRCH), Image.LANCZOS)
    _page_cache[pid] = im
    if len(_page_cache) > 4:
        _page_cache.popitem(last=False)
    return im


def overlay_img(pid: str) -> Image.Image:
    if pid not in _overlay_cache:
        p = BUILD / "overlays" / f"{pid}.png"
        if not p.exists():
            raise SystemExit(f"missing overlay {p} — run node video/capture.mjs pages")
        _overlay_cache[pid] = Image.open(p).convert("RGBA").resize((W, H), Image.LANCZOS)
    return _overlay_cache[pid]


def clip_files(name: str) -> list[pathlib.Path]:
    if name not in _clip_files:
        d = CLIPS / name
        files = sorted(d.glob("f*.jpg"))
        if not files:
            raise SystemExit(f"missing clip frames in {d} — run node video/capture_clips.mjs")
        _clip_files[name] = files
    return _clip_files[name]


def clip_frame(name: str, idx: int) -> Image.Image:
    files = clip_files(name)
    idx = max(0, min(len(files) - 1, idx))
    key = (name, idx)
    if key in _clip_cache:
        _clip_cache.move_to_end(key)
        return _clip_cache[key]
    im = Image.open(files[idx]).convert("RGB")
    _clip_cache[key] = im
    if len(_clip_cache) > 10:
        _clip_cache.popitem(last=False)
    return im


SENT_TIMES = {}
_times_path = BUILD / "sentence_times.json"
if _times_path.exists():
    SENT_TIMES = json.loads(_times_path.read_text(encoding="utf-8"))

_cap_cache: dict[str, Image.Image] = {}


def caption_img(cid: str) -> Image.Image | None:
    if cid not in _cap_cache:
        p = BUILD / "captions" / f"{cid}.png"
        if not p.exists():
            return None
        _cap_cache[cid] = Image.open(p).convert("RGBA").resize((W, H), Image.LANCZOS)
    return _cap_cache[cid]


def build_caption_plan() -> dict[int, list[tuple[float, float, str]]]:
    """每镜：[(相对镜头的显示起点, 显示终点, caption id)]"""
    plan: dict[int, list[tuple[float, float, str]]] = {}
    n = 0
    for shot in CFG["shots"]:
        parts = [x.strip("，, ") for x in shot["narration"].split("／") if x.strip("，, ")]
        spans = SENT_TIMES.get(str(shot["id"]), [])
        items = []
        for k, _part in enumerate(parts):
            n += 1
            cid = f"c{n:03d}"
            st = float(spans[k][0]) if k < len(spans) else 0.0
            en = float(spans[k][1]) if k < len(spans) else st
            items.append((st, en, cid))
        # 显示窗口：本句起点 → 下一句起点（末句到本镜结束）
        out = []
        for k, (st, en, cid) in enumerate(items):
            nxt = items[k + 1][0] if k + 1 < len(items) else None
            start = 0.0 if k == 0 else st
            end = (nxt if nxt is not None else en + 0.55)
            out.append((start, end, cid))
        plan[shot["id"]] = out
    return plan


CAP_PLAN = build_caption_plan()
LEAD = 0.25
CAP_XFADE = 0.12


def caption_at(shot_id: int, t: float) -> Image.Image | None:
    items = CAP_PLAN.get(shot_id, [])
    if not items:
        return None
    tt = t - LEAD
    active = None
    for k, (start, end, cid) in enumerate(items):
        if start <= tt < end or (k == 0 and tt < start):
            active = (k, cid)
            break
    if active is None:
        active = (len(items) - 1, items[-1][2])
    k, cid = active
    img = caption_img(cid)
    start, _end, _ = items[k]
    a = 1.0
    if k > 0 and tt < start + CAP_XFADE:
        a = max(0.0, min(1.0, (tt - start) / CAP_XFADE))
    m = tt + CAP_XFADE
    # 句尾交叉到下一句
    if k + 1 < len(items):
        nstart = items[k + 1][0]
        if tt > nstart - CAP_XFADE and tt >= items[k][0]:
            a = max(0.0, min(1.0, (nstart - tt) / CAP_XFADE))
            nxt = caption_img(items[k + 1][2])
            if nxt is not None and a < 1.0:
                if img is None:
                    return nxt
                base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                base = Image.alpha_composite(base, nxt)
                tmp = img.copy()
                tmp.putalpha(tmp.getchannel("A").point(lambda v: int(v * a)))
                return Image.alpha_composite(base, tmp)
    if img is None:
        return None
    if a < 0.999:
        img = img.copy()
        img.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
    return img


def sub_img(sid: int) -> Image.Image | None:
    p = BUILD / "subs" / f"sub{sid:02d}.png"
    if not p.exists():
        return None
    return Image.open(p).convert("RGBA").resize((W, H), Image.LANCZOS)


def shot_bounds(system: dict, dur: float) -> list[float]:
    weights = system["weights"]
    out, acc = [0.0], 0.0
    for w in weights:
        acc += w
        out.append(dur * acc)
    out[-1] = dur
    return out


def state_mix(t: float, bounds: list[float], xf: float):
    n = len(bounds) - 1
    if xf > 0:
        for k in range(1, n):
            b = bounds[k]
            if abs(t - b) <= xf / 2:
                a = 0.5 + (t - b) / xf
                return k - 1, k, min(1.0, max(0.0, a))
    i = max(0, min(n - 1, bisect.bisect_right(bounds, t) - 1))
    return i, None, 0.0


def kb(system: dict, dur: float, t: float):
    k = system["kenburns"]
    p = min(1.0, max(0.0, t / max(1e-6, dur)))
    z = k["z0"] + (k["z1"] - k["z0"]) * p
    return z, k["pan"][0] * p, k["pan"][1] * p


def sample(im: Image.Image, z: float, dx: float, dy: float) -> Image.Image:
    """按 zoom/pan 裁窗并缩放到 1080x1920；源图 2160x3840 或 1080x1920 都可以。"""
    sw, sh = im.size
    cw, ch = sw / z, sh / z
    cx = sw / 2 + dx * (sw / W)
    cy = sh / 2 + dy * (sh / H)
    l = max(0.0, min(sw - cw, cx - cw / 2))
    t = max(0.0, min(sh - ch, cy - ch / 2))
    box = (int(round(l)), int(round(t)), int(round(l + cw)), int(round(t + ch)))
    return im.crop(box).resize((W, H), Image.LANCZOS)


def render_state(system: dict, idx: int, frame: int, starts: list[int], z, dx, dy) -> Image.Image:
    """渲染一个状态（底片 + 覆盖层），不含字幕。"""
    st = system["states"][idx]
    overlay = None
    if system.get("clip"):
        base = clip_frame(system["clip"], system.get("clipOffset", 0) + frame)
        overlay = st
    elif isinstance(st, dict):
        if "page" in st:
            base = page_img(st["page"])
        else:
            base = clip_frame(st["clip"], st.get("offset", 0) + (frame - starts[idx]))
            overlay = st.get("overlay")
    else:
        base = page_img(st)

    img = sample(base, z, dx, dy)
    if overlay:
        img = Image.alpha_composite(img.convert("RGBA"), overlay_img(overlay)).convert("RGB")
    return img


def compose_frame(system: dict, sid: int, f_local: int) -> Image.Image:
    dur = system["_dur"]
    t = f_local / FPS
    bounds = shot_bounds(system, dur)
    starts = [int(round(b * FPS)) for b in bounds]
    xf = system.get("xfade", 0.2)
    i, j, a = state_mix(t, bounds, xf)
    z, dx, dy = kb(system, dur, t)
    img = render_state(system, i, f_local, starts, z, dx, dy)
    if j is not None and a > 0.001:
        img2 = render_state(system, j, f_local, starts, z, dx, dy)
        img = Image.blend(img, img2, a)
    cap = None if not CFG["shots_by_id"][sid].get("captions", True) else caption_at(sid, t)
    if cap is not None:
        img = Image.alpha_composite(img.convert("RGBA"), cap).convert("RGB")
    return img


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def render_stills(tl: dict, times: list[float]):
    (BUILD / "check").mkdir(parents=True, exist_ok=True)
    spans = [(s["start_frame"], s["start_frame"] + s["frames"], s) for s in tl["shots"]]
    for t in times:
        f = int(round(t * FPS))
        for a, b, shot in spans:
            if a <= f < b:
                system = dict(SYS_SHOTS[shot["id"]])
                system["_dur"] = shot["dur"]
                im = compose_frame(system, shot["id"], f - a)
                p = BUILD / "check" / f"f{t:06.2f}_shot{shot['id']}.png"
                im.save(p)
                print("still", p)
                break


def write_srt(tl: dict):
    def ts(x: float) -> str:
        ms = int(round(x * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    caps_json = BUILD / "captions.json"
    captions = json.loads(caps_json.read_text(encoding="utf-8")) if caps_json.exists() else {}
    lines = []
    n = 0
    for shot in tl["shots"]:
        base = shot["start_frame"] / tl["fps"]
        for start, end, cid in CAP_PLAN.get(shot["id"], []):
            n += 1
            lines.append(str(n))
            lines.append(f"{ts(base + LEAD + start)} --> {ts(base + LEAD + end)}")
            lines.append(captions.get(cid, ""))
            lines.append("")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "subtitles.srt").write_text("\n".join(lines), encoding="utf-8")
    print("srt ->", OUT / "subtitles.srt")


def render_video(tl: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / "three_domain_1080x1920.mp4"
    mix = BUILD / "mix.wav"
    if not mix.exists():
        raise SystemExit(f"missing {mix} — run video/audio.py first")

    cmd = [
        ffmpeg_exe(), "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(mix),
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-maxrate", "16M", "-bufsize", "32M", "-pix_fmt", "yuv420p", "-g", "60",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart", str(dst),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    t0 = time.time()
    total = tl["frames"]
    try:
        for shot in tl["shots"]:
            system = dict(SYS_SHOTS[shot["id"]])
            system["_dur"] = shot["dur"]
            for f in range(shot["frames"]):
                img = compose_frame(system, shot["id"], f)
                proc.stdin.write(img.tobytes())
                if f % 60 == 0:
                    done = shot["start_frame"] + f
                    print(f"  shot {shot['id']}  {done}/{total} frames  {time.time()-t0:5.1f}s", flush=True)
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        code = proc.wait()
        if code != 0:
            print(err, file=sys.stderr)
            raise SystemExit(f"ffmpeg failed ({code})")
        if err.strip():
            print("[ffmpeg]", err.strip()[-2000:], file=sys.stderr)
    finally:
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            err = proc.stderr.read().decode("utf-8", "replace")
            if err.strip():
                print("[ffmpeg]", err.strip()[-3000:], file=sys.stderr)
            proc.wait(timeout=60)
        except Exception:  # noqa: BLE001
            pass
        if proc.poll() is None:
            proc.kill()
    print(f"video -> {dst}   ({time.time()-t0:.1f}s)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", type=str, default="")
    ap.add_argument("--video", action="store_true")
    args = ap.parse_args()

    tl = tl_mod.build(CFG)
    print(f"timeline {tl['duration']:.2f}s / {tl['frames']} frames")
    write_srt(tl)
    if args.stills:
        render_stills(tl, [float(x) for x in args.stills.split(",") if x.strip()])
    if args.video:
        render_video(tl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
