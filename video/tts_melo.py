"""MeloTTS 中文女声合成（Python 3.11 + GPU，HF 模型自动下载）。

按「／」把每镜旁白切成句子分别合成，句间插 0.28s 气口再拼起来——
既能控制停顿，也避免整段长文本被引擎截断。

产物：build/melo_raw/nNN.wav（44.1kHz 单声道）；重采样与归一见 tts.py。
用法： py -3.11 video/tts_melo.py [镜号]
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"
RAW = BUILD / "melo_raw"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
VOICE = CFG.get("voice", {})
SPEED = float(VOICE.get("meloSpeed", 1.2))
GAP = 0.28


def read_wav(path: pathlib.Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    return x, sr


def write_wav(path: pathlib.Path, x: np.ndarray, sr: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def main() -> int:
    from melo.api import TTS

    only = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    RAW.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    model = TTS(language="ZH", device=VOICE.get("device", "cuda:0"))
    spk = model.hps.data.spk2id["ZH"]
    print(f"melo loaded in {time.time()-t0:.1f}s  speed={SPEED}")

    times: dict[int, list] = {}
    for shot in CFG["shots"]:
        sid = shot["id"]
        if only and sid != only:
            continue
        parts = [p.strip("，, ") for p in shot["narration"].split("／") if p.strip("，, ")]
        chunks, sr, spans = [], 0, []
        cursor = 0.0
        for k, part in enumerate(parts):
            tmp = RAW / f"_tmp_{sid:02d}_{k}.wav"
            model.tts_to_file(part, spk, str(tmp), speed=SPEED)
            x, sr = read_wav(tmp)
            tmp.unlink(missing_ok=True)
            chunks.append(x)
            spans.append([round(cursor, 3), round(cursor + len(x) / sr, 3)])
            cursor += len(x) / sr + GAP
        gap = np.zeros(int(sr * GAP), dtype=np.float32)
        out = []
        for k, ch in enumerate(chunks):
            out.append(ch)
            if k < len(chunks) - 1:
                out.append(gap)
        joined = np.concatenate(out) if out else np.zeros(1, dtype=np.float32)
        dst = RAW / f"n{sid:02d}.wav"
        write_wav(dst, joined, sr)
        times[sid] = spans
        print(f"  n{sid:02d}  {len(joined)/sr:5.2f}s  sentences={len(parts)}  {shot['narration'][:24]}")
    if only:
        tj = BUILD / "sentence_times.json"
        prev = json.loads(tj.read_text(encoding="utf-8")) if tj.exists() else {}
        prev.update({str(k): v for k, v in times.items()})
        tj.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        (BUILD / "sentence_times.json").write_text(
            json.dumps({str(k): v for k, v in times.items()}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    print("melo raw ->", RAW)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
