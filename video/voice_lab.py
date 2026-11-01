"""配音体检 + 广播级后处理。

用途：不再靠"听着像不像"，而是量出「有气无力」的几个客观指标，再挑念法：
  · 语速 chars/s
  · 基频 F0 均值与标准差（平 = 有气无力；标准差大 = 有起伏）
  · 能量动态 RMS 标准差（压得太死 = 没劲）
  · 有声段占比（停顿太多也显得虚）

然后对胜出的那条跑一遍广播级链：
  高通 90Hz → 3kHz 存在感 +2.5dB → 压缩 2.5:1 → loudnorm 到 -15 LUFS / -1.2 dBTP

用法：
  python video/voice_lab.py review <wav...>       # 只出指标
  python video/voice_lab.py polish <in> <out>     # 跑后处理链
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"
SR = 24000          # 体检测量用（降采样，够用且快）


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def load_mono(path: pathlib.Path, sr: int = SR) -> np.ndarray:
    tmp = BUILD / "_lab.tmp.wav"
    subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-i", str(path),
                    "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", str(tmp)], check=True)
    with wave.open(str(tmp), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    tmp.unlink(missing_ok=True)
    return x


def frames(x: np.ndarray, win: int, hop: int):
    n = 1 + max(0, (x.size - win) // hop)
    for i in range(n):
        yield x[i * hop: i * hop + win]


def f0_track(x: np.ndarray, sr: int = SR, fmin: float = 70.0, fmax: float = 420.0) -> np.ndarray:
    """自相关基频（只保留有声帧）。"""
    win, hop = int(0.030 * sr), int(0.010 * sr)
    lo, hi = int(sr / fmax), int(sr / fmin)
    out = []
    for fr in frames(x, win, hop):
        e = float(np.sqrt(np.mean(fr ** 2)))
        if e < 0.01:
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, mode="full")[fr.size - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        if seg.size == 0:
            continue
        k = int(np.argmax(seg)) + lo
        if ac[k] / ac[0] > 0.32:
            out.append(sr / k)
    return np.array(out, dtype=np.float32)


def review(paths: list[pathlib.Path]) -> dict:
    rows = {}
    for p in paths:
        x = load_mono(p)
        dur = x.size / SR
        voiced = np.abs(x) > 0.01
        f0 = f0_track(x)
        # 能量动态：按 50ms 块算 RMS 的标准差（dB）
        blk = int(0.05 * SR)
        rms = np.array([np.sqrt(np.mean(c ** 2)) for c in frames(x, blk, blk) if c.size])
        rms_db = 20 * np.log10(np.maximum(rms, 1e-6))
        rows[p.name] = {
            "dur": round(float(dur), 2),
            "voiced_ratio": round(float(voiced.mean()), 3),
            "f0_mean": round(float(np.median(f0)), 1) if f0.size else 0.0,
            "f0_std": round(float(np.std(f0)), 1) if f0.size else 0.0,
            "rms_std_db": round(float(np.std(rms_db)), 2),
            "peak_db": round(float(20 * np.log10(max(1e-6, np.abs(x).max()))), 2),
        }
    return rows


def polish(src: pathlib.Path, dst: pathlib.Path, quiet: bool = False) -> None:
    chain = (
        "highpass=f=90,"
        "equalizer=f=3000:t=q:w=1.1:g=2.6,"
        "equalizer=f=220:t=q:w=1.2:g=-1.6,"
        "acompressor=threshold=-20dB:ratio=2.6:attack=8:release=170:makeup=1,"
        "loudnorm=I=-15:TP=-1.2:LRA=7"
    )
    subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-i", str(src),
                    "-af", chain, "-ar", "48000", "-ac", "1", str(dst)], check=True)
    if not quiet:
        print("polished ->", dst)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "review":
        rows = review([pathlib.Path(a) for a in sys.argv[2:]])
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif cmd == "polish":
        polish(pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]))
    else:
        print("unknown command", cmd)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
