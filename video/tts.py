"""生成 9 段旁白（edge-tts 优先，SAPI 兜底），统一到 48k 单声道 16bit 并归一到 -18 dBFS。

用法： python video/tts.py  [--voice zh-CN-XiaochenNeural] [--rate +5%]
产物： video/build/n01.wav … n09.wav
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import shutil
import subprocess
import sys
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

SR = 48000
VOICE = CFG.get("voice", {}).get("name", "zh-CN-XiaoxiaoNeural")
RATE = CFG.get("voice", {}).get("rate", "-2%")
PITCH = CFG.get("voice", {}).get("pitch", "-6Hz")
TARGET_RMS_DB = -18.0
PEAK_DB = -1.5


def ffmpeg_exe() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def normalize_to_wav(src: pathlib.Path, dst: pathlib.Path) -> float:
    """解码任意音频 -> 48k 单声道 16bit，归一 RMS 并限峰。返回时长。"""
    tmp = dst.with_suffix(".raw.wav")
    cmd = [ffmpeg_exe(), "-y", "-v", "error", "-i", str(src),
           "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(tmp)]
    subprocess.run(cmd, check=True)

    with wave.open(str(tmp), "rb") as w:
        n = w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if x.size == 0:
        raise SystemExit(f"empty audio: {src}")

    rms = float(np.sqrt(np.mean(x ** 2)) + 1e-12)
    gain = (10 ** (TARGET_RMS_DB / 20.0)) / rms
    x = x * gain
    peak = float(np.max(np.abs(x)))
    limit = 10 ** (PEAK_DB / 20.0)
    if peak > limit:
        x = x * (limit / peak)

    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    tmp.unlink(missing_ok=True)
    return len(x) / SR


def edge_tts_synth(text: str, mp3: pathlib.Path) -> None:
    import edge_tts

    async def go():
        comm = edge_tts.Communicate(text, voice=VOICE, rate=RATE, pitch=PITCH)
        await comm.save(str(mp3))

    asyncio.run(go())


def sapi_synth(text: str, wav: pathlib.Path) -> None:
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SelectVoice('Microsoft Huihui Desktop'); "
        f"$s.SetOutputToWaveFile('{wav}'); "
        f"$s.Speak('{text}'); "
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)


def synth_melo() -> int:
    """调 py -3.11 跑 MeloTTS 出原始 wav，再统一重采样/归一。"""
    raw = BUILD / "melo_raw"
    raw.mkdir(parents=True, exist_ok=True)
    py311 = shutil.which("py") or "py"
    cmd = [py311, "-3.11", str(ROOT / "tts_melo.py")]
    print("[melo]", " ".join(cmd))
    subprocess.run(cmd, check=True)
    for shot in CFG["shots"]:
        sid = shot["id"]
        dst = BUILD / f"n{sid:02d}.wav"
        dur = normalize_to_wav(raw / f"n{sid:02d}.wav", dst)
        print(f"  n{sid:02d}  {dur:5.2f}s  [melo]")
    print("voice = melo  speed", CFG.get("voice", {}).get("meloSpeed", 1.2))
    return 0


def main() -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    engine = CFG.get("voice", {}).get("engine", "edge")
    if engine == "melo":
        return synth_melo()

    mode = "edge-tts"
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("[warn] edge-tts 不可用，回退 SAPI", file=sys.stderr)
        mode = "sapi"

    for shot in CFG["shots"]:
        sid = shot["id"]
        text = shot["narration"].replace("／", "，").replace("／", "，").strip()
        out_wav = BUILD / f"n{sid:02d}.wav"
        tmp_mp3 = BUILD / f"n{sid:02d}.mp3"
        tmp_wav = BUILD / f"n{sid:02d}.src.wav"

        ok = False
        if mode == "edge-tts":
            try:
                edge_tts_synth(text, tmp_mp3)
                dur = normalize_to_wav(tmp_mp3, out_wav)
                ok = True
            except Exception as e:  # noqa: BLE001
                print(f"[warn] shot {sid} edge-tts 失败：{e}；回退 SAPI", file=sys.stderr)
                mode = "sapi"
        if not ok:
            sapi_synth(text, tmp_wav)
            dur = normalize_to_wav(tmp_wav, out_wav)

        tmp_mp3.unlink(missing_ok=True)
        tmp_wav.unlink(missing_ok=True)
        print(f"  n{sid:02d}  {dur:5.2f}s  [{mode}]  {text}")

    print("voice =", mode, VOICE, RATE, PITCH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
