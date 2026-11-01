"""时间轴：把旁白实测时长 + config 变成每一镜的起止帧。

以配音为准（plan §5.4）： shot = max(旁白 + lead + tail, minDur)，再整体补齐/收紧到 65–78s。
"""
from __future__ import annotations

import json
import pathlib
import wave

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"

LEAD = 0.25            # 旁白比画面入点晚 0.25s
TARGET_MIN = 66.0
TARGET_MAX = 76.0


def wav_duration(path: pathlib.Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def narration_durations(cfg: dict) -> list[float]:
    out = []
    for shot in cfg["shots"]:
        p = BUILD / f"n{shot['id']:02d}.wav"
        if not p.exists():
            raise SystemExit(f"missing narration {p} — run video/tts.py first")
        out.append(wav_duration(p))
    return out


def build(cfg: dict | None = None) -> dict:
    cfg = cfg or json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    fps = cfg["video"]["fps"]
    narr = narration_durations(cfg)

    shots = []
    for shot, nd in zip(cfg["shots"], narr):
        dur = max(nd + LEAD + shot.get("tail", 0.45), shot.get("minDur", 4.0))
        shots.append({"id": shot["id"], "slug": shot["slug"], "narr": nd, "dur": dur})

    total = sum(s["dur"] for s in shots)
    # 补齐 / 收紧
    pad_order = [1, 3, 5, 7]  # 镜 2 / 4 / 6 / 8
    while total < TARGET_MIN:
        before = total
        for i in pad_order:
            if total >= TARGET_MIN:
                break
            shots[i]["dur"] += 0.5
            total += 0.5
        if total == before:
            break
    while total > TARGET_MAX:
        before_cut = total
        # 只收气口，不动旁白
        for i in sorted(range(len(shots)), key=lambda k: -shots[k]["dur"]):
            if total <= TARGET_MAX:
                break
            floor = shots[i]["narr"] + LEAD + 0.2
            cut = min(0.4, shots[i]["dur"] - floor)
            if cut > 0.01:
                shots[i]["dur"] -= cut
                total -= cut
        if total >= before_cut - 1e-6:
            break

    # 量化到整帧
    start = 0
    for s in shots:
        frames = int(round(s["dur"] * fps))
        s["frames"] = frames
        s["start_frame"] = start
        s["dur"] = frames / fps
        s["narr_start"] = s["dur"] * 0 + LEAD
        start += frames

    return {
        "fps": fps,
        "frames": start,
        "duration": start / fps,
        "shots": shots,
    }


if __name__ == "__main__":
    tl = build()
    print(f"total {tl['duration']:.2f}s  {tl['frames']} frames @ {tl['fps']}fps")
    for s in tl["shots"]:
        print(f"  shot {s['id']}  {s['dur']:6.2f}s  narr {s['narr']:5.2f}s  start_frame {s['start_frame']}")
