"""BGM 编曲替换：把原来的低频 drone 换成 lo-fi 钢琴琶音 + 轻鼓点。

设计（对齐抖音知识区/考据类视频的听感）：
  · 78 BPM，A 小调，Am–F–C–G 四小节循环
  · 软 pad（三和弦 + 轻微 detune，慢起音）
  · 八分音符钢琴琶音，带附点八分延迟（空间感）
  · 低音 sine 铺底 + 轻 kick / clap / hat（鼓组压得很低，不抢旁白）
所有声音都是现场合成，不含第三方素材。
"""
from __future__ import annotations

import json
import pathlib
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SR = 48000
RNG = np.random.default_rng(20261101)

BPM = 78.0
SPB = 60.0 / BPM
BAR = 4 * SPB

# Am / F / C / G —— (三和弦 midi, 低音 midi)
CHORDS = [
    ([57, 60, 64], 45),
    ([53, 57, 60], 41),
    ([48, 52, 55], 36),
    ([55, 59, 62], 43),
]


def midi_hz(m: float) -> float:
    return 440.0 * (2.0 ** ((m - 69.0) / 12.0))


def lowpass(x: np.ndarray, k: int) -> np.ndarray:
    k = max(1, int(k))
    return np.convolve(x, np.ones(k, dtype=np.float32) / k, mode="same").astype(np.float32)


def highpass(x: np.ndarray, k: int) -> np.ndarray:
    return (x - lowpass(x, k)).astype(np.float32)


def add(buf: np.ndarray, start: int, wave_data: np.ndarray) -> None:
    if start >= buf.size:
        return
    end = min(buf.size, start + wave_data.size)
    buf[start:end] += wave_data[: end - start]


def pluck(freq: float, dur: float, gain: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    env = np.exp(-t / 0.26).astype(np.float32)
    body = (np.sin(2 * np.pi * freq * t) + 0.32 * np.sin(2 * np.pi * freq * 2 * t)
            + 0.12 * np.sin(2 * np.pi * freq * 3 * t)).astype(np.float32)
    attack = np.clip(t / 0.006, 0, 1).astype(np.float32)
    return (body * env * attack * gain).astype(np.float32)


def pad_note(freq: float, dur: float, gain: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    a = np.clip(t / 0.9, 0, 1)
    r = np.clip((dur - t) / 0.8, 0, 1)
    env = (a * r).astype(np.float32)
    body = (np.sin(2 * np.pi * (freq - 0.4) * t) + np.sin(2 * np.pi * (freq + 0.5) * t)
            + 0.5 * np.sin(2 * np.pi * freq * 1.5 * t)).astype(np.float32)
    return (body * env * gain).astype(np.float32)


def bass_note(freq: float, dur: float, gain: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    env = (np.clip(t / 0.02, 0, 1) * np.exp(-t / 0.55)).astype(np.float32)
    return (np.sin(2 * np.pi * freq * t) * env * gain).astype(np.float32)


def kick(gain: float) -> np.ndarray:
    n = int(0.22 * SR)
    t = np.arange(n, dtype=np.float32) / SR
    f = 92.0 * np.exp(-t / 0.045) + 44.0
    env = np.exp(-t / 0.085).astype(np.float32)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * env * gain).astype(np.float32)


def clap(gain: float) -> np.ndarray:
    n = int(0.16 * SR)
    t = np.arange(n, dtype=np.float32) / SR
    noise = RNG.standard_normal(n).astype(np.float32)
    noise = highpass(lowpass(noise, 6), 30)
    bursts = np.zeros(n, dtype=np.float32)
    for off, g in ((0.0, 1.0), (0.012, 0.7), (0.026, 0.45)):
        burst = np.exp(-np.maximum(0, t - off) / 0.028).astype(np.float32) * g
        bursts += np.where(t >= off, burst, 0.0)
    return (noise * bursts * gain).astype(np.float32)


def hat(gain: float) -> np.ndarray:
    n = int(0.06 * SR)
    t = np.arange(n, dtype=np.float32) / SR
    noise = RNG.standard_normal(n).astype(np.float32)
    noise = highpass(noise, 12)
    env = np.exp(-t / 0.018).astype(np.float32)
    return (noise * env * gain).astype(np.float32)


def compose_bgm(total: float) -> np.ndarray:
    n = int(total * SR)
    pad = np.zeros(n, dtype=np.float32)
    plk = np.zeros(n, dtype=np.float32)
    bass = np.zeros(n, dtype=np.float32)
    drums = np.zeros(n, dtype=np.float32)

    bars = int(np.ceil(total / BAR)) + 1
    for b in range(bars):
        t0 = b * BAR
        tones, root = CHORDS[b % 4]
        i0 = int(t0 * SR)
        add(pad, i0, pad_note(midi_hz(tones[0] + 12), BAR * 1.05, 0.10))
        add(pad, i0, pad_note(midi_hz(tones[1] + 12), BAR * 1.05, 0.07))
        add(pad, i0, pad_note(midi_hz(tones[2] + 12), BAR * 1.05, 0.07))
        for k in (0, 2):
            add(bass, int((t0 + k * SPB) * SR), bass_note(midi_hz(root), SPB * 1.9, 0.42))
        seq = [tones[0] + 12, tones[1] + 12, tones[2] + 12, tones[0] + 24,
               tones[2] + 12, tones[1] + 12, tones[0] + 12, tones[1] + 12]
        for k, m in enumerate(seq):
            accent = 1.0 if k % 4 == 0 else 0.72
            add(plk, int((t0 + k * SPB / 2) * SR), pluck(midi_hz(m), 0.55, 0.20 * accent))
        for k in (0, 2):
            add(drums, int((t0 + k * SPB) * SR), kick(0.30))
        for k in (1, 3):
            add(drums, int((t0 + k * SPB) * SR), clap(0.16))
        for k in range(8):
            add(drums, int((t0 + k * SPB / 2) * SR), hat(0.075 if k % 2 == 0 else 0.045))

    # 琶音加一条附点八分延迟，做出空间感
    d = int(SPB * 0.75 * SR)
    echo = np.zeros(n, dtype=np.float32)
    echo[d:] = plk[: n - d] * 0.34
    plk = plk + lowpass(echo, 4)

    bed = pad + plk + bass + drums
    return bed.astype(np.float32)


def rms_db(x: np.ndarray) -> float:
    return 20.0 * np.log10(float(np.sqrt(np.mean(x ** 2)) + 1e-12))


def db2lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


if __name__ == "__main__":
    import sys

    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    bed = compose_bgm(seconds)
    target = -24.0
    bed = bed * db2lin(target - rms_db(bed))
    peak = float(np.max(np.abs(bed)))
    if peak > db2lin(-3.0):
        bed *= db2lin(-3.0) / peak
    BUILD.mkdir(parents=True, exist_ok=True)
    out = BUILD / "bgm_preview.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(bed, -1, 1) * 32767).astype("<i2").tobytes())
    print(f"bgm preview -> {out}  {seconds:.0f}s  rms {rms_db(bed):.2f} dBFS  peak {20*np.log10(max(peak,1e-9)):.2f}")
