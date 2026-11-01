"""BGM / 音效全部现场合成（零第三方素材），并与旁白混成 build/mix.wav。

用法： python video/audio.py
依赖： video/build/n01..n09.wav（先跑 tts.py）+ timeline.py
"""
from __future__ import annotations

import json
import pathlib
import wave

import numpy as np

import bgm_compose
import timeline as tl_mod

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
AUD = CFG["audio"]
SR = 48000
RNG = np.random.default_rng(20261101)


def read_wav(path: pathlib.Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1, f"bad wav {path}"
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    return x


def db2lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def rms_db(x: np.ndarray) -> float:
    return 20.0 * np.log10(float(np.sqrt(np.mean(x ** 2)) + 1e-12))


def lowpass(x: np.ndarray, k: int) -> np.ndarray:
    k = max(1, int(k))
    kernel = np.ones(k, dtype=np.float32) / k
    return np.convolve(x, kernel, mode="same").astype(np.float32)


def highpass(x: np.ndarray, k: int) -> np.ndarray:
    return (x - lowpass(x, k)).astype(np.float32)


def normalize(x: np.ndarray, target_db: float) -> np.ndarray:
    cur = rms_db(x)
    return (x * db2lin(target_db - cur)).astype(np.float32)


# ---------------- BGM ----------------
def make_bgm(total: float, voice_rms: float, shot_starts: dict[int, float]) -> np.ndarray:
    """lo-fi 钢琴琶音 + 轻鼓点（见 bgm_compose.py），按旁白略低 -24 dB 铺底。"""
    n = int(total * SR)
    if AUD.get("bgm", "lofi") in ("none", "off", "no"):
        return np.zeros(n, dtype=np.float32)
    bed = bgm_compose.compose_bgm(total)
    if bed.size < n:
        bed = np.pad(bed, (0, n - bed.size))
    bed = bed[:n]

    target = voice_rms + AUD["bgmRelativeDb"]   # bgmRelativeDb 本身是负数
    bed = normalize(bed, target)

    # 镜 7 之后抬 3 dB，结尾淡出
    lift_from = shot_starts.get(AUD["bgmLiftFromShot"], total)
    ramp = int(0.8 * SR)
    env = np.ones(n, dtype=np.float32)
    i0 = int(lift_from * SR)
    if i0 < n:
        env[i0:] = db2lin(AUD["bgmLiftDb"])
        if i0 + ramp < n:
            env[i0:i0 + ramp] = np.linspace(1.0, db2lin(AUD["bgmLiftDb"]), ramp)
    fade_n = int(AUD["fadeOut"] * SR)
    if fade_n < n:
        env[n - fade_n:] *= np.linspace(1.0, 0.0, fade_n)
    return (bed * env).astype(np.float32)


# ---------------- SFX ----------------
def sfx_whoosh(dur=0.85) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    x = RNG.standard_normal(n).astype(np.float32)
    x = lowpass(x, 90)
    env = np.exp(-((t - 0.28) ** 2) / 0.020).astype(np.float32)
    return normalize((x * env).astype(np.float32), -18.0)


def sfx_ping(dur=0.75) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    x = (np.sin(2 * np.pi * 1240 * t) * np.exp(-5.5 * t)
         + 0.55 * np.sin(2 * np.pi * 1860 * t) * np.exp(-8.0 * t)
         + 0.25 * np.sin(2 * np.pi * 620 * t) * np.exp(-4.0 * t)).astype(np.float32)
    return normalize(x, -18.0)


def sfx_strike(dur=0.42) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    noise = lowpass(RNG.standard_normal(n).astype(np.float32), 12)
    x = (np.tanh(3.0 * (noise * np.exp(-26 * t) + 0.6 * np.sin(2 * np.pi * 190 * t) * np.exp(-14 * t))))
    return normalize(x.astype(np.float32), -17.0)


def sfx_crackle(dur=1.05) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    noise = RNG.standard_normal(n).astype(np.float32)
    gate = np.zeros(n, dtype=np.float32)
    step = 97
    for i in range(0, n, step):
        if RNG.random() < 0.35:
            gate[i:i + step] = RNG.random()
    x = highpass(noise, 8) * gate
    env = np.exp(-2.2 * t).astype(np.float32)
    return normalize((x * env).astype(np.float32), -18.0)


def sfx_impact(dur=1.15) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    sub = np.sin(2 * np.pi * 46 * t) * np.exp(-3.4 * t)
    click = lowpass(RNG.standard_normal(n).astype(np.float32), 6) * np.exp(-30 * t)
    x = np.tanh(2.2 * (sub + 0.45 * click)).astype(np.float32)
    return normalize(x, -14.0)


SFX = {"whoosh": sfx_whoosh, "ping": sfx_ping, "strike": sfx_strike,
       "crackle": sfx_crackle, "impact": sfx_impact}


def main() -> int:
    tl = tl_mod.build(CFG)
    total = tl["duration"]
    n = int(total * SR)

    voice = np.zeros(n, dtype=np.float32)
    for shot in tl["shots"]:
        x = read_wav(BUILD / f"n{shot['id']:02d}.wav")
        i = int((shot["start_frame"] / tl["fps"] + 0.25) * SR)
        j = min(n, i + x.size)
        if j > i:
            voice[i:j] += x[: j - i]
    v_rms = rms_db(voice[voice != 0]) if np.any(voice != 0) else -18.0

    shot_starts = {s["id"]: s["start_frame"] / tl["fps"] for s in tl["shots"]}
    bed = make_bgm(total, v_rms, shot_starts)

    sfx_bus = np.zeros(n, dtype=np.float32)
    for shot in tl["shots"]:
        cfg_shot = next(s for s in CFG["shots"] if s["id"] == shot["id"])
        start = shot_starts[shot["id"]]
        for cue in ([] if not AUD.get("sfx", True) else cfg_shot.get("sfx", [])):
            wave_x = SFX[cue["type"]]()
            gain = db2lin(cue["db"] - rms_db(wave_x))
            seg = wave_x * gain
            # 瞬态音效只有 RMS 会被爆掉：给每个 cue 加一个 -6 dBFS 的峰上限
            pk = float(np.max(np.abs(seg)))
            cap = db2lin(-6.0)
            if pk > cap:
                seg = seg * (cap / pk)
            at = start + float(cue["at"]) * shot["dur"]
            i = int(at * SR)
            j = min(n, i + seg.size)
            if j > i:
                sfx_bus[i:j] += seg[: j - i]

    if AUD.get("polish", True) and AUD.get("bgm", "lofi") in ("none", "off", "no"):
        # 只有人声时，先过一遍广播级后处理再出场
        import voice_lab
        tmp_in = BUILD / "_voice_raw.wav"
        tmp_out = BUILD / "_voice_polish.wav"
        with wave.open(str(tmp_in), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(voice, -1, 1) * 32767).astype("<i2").tobytes())
        voice_lab.polish(tmp_in, tmp_out)
        with wave.open(str(tmp_out), "rb") as w:
            vx = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        if vx.size >= n:
            voice = vx[:n]
        else:
            voice = np.pad(vx, (0, n - vx.size))
        print(f"  voice 后处理：peak {rms_db(voice):.2f} dBFS rms")
        tmp_in.unlink(missing_ok=True)
        tmp_out.unlink(missing_ok=True)

    mix = voice + bed + sfx_bus
    fade_n = int(AUD["fadeOut"] * SR)
    mix[n - fade_n:] *= np.linspace(1.0, 0.0, fade_n)
    peak = float(np.max(np.abs(mix)))
    if peak > db2lin(-1.0):
        mix *= db2lin(-1.0) / peak
        print(f"[mix] peak 限幅到 -1 dBFS（原 {20*np.log10(peak):.2f} dBFS）")

    stereo = np.stack([mix, mix], axis=1)
    out = BUILD / "mix.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(stereo, -1, 1) * 32767).astype("<i2").tobytes())

    print(f"mix -> {out}")
    print(f"  total     {total:6.2f}s")
    print(f"  voice rms {v_rms:6.2f} dBFS")
    print(f"  bed  rms  {rms_db(bed):6.2f} dBFS   (相对旁白 {rms_db(bed)-v_rms:+.1f} dB)")
    print(f"  sfx  rms  {rms_db(sfx_bus[sfx_bus!=0]) if np.any(sfx_bus!=0) else float('nan'):6.2f} dBFS")
    print(f"  peak      {20*np.log10(max(peak,1e-9)):6.2f} dBFS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
