"""配音 A/B：同一句话，几条念法都过同一条广播链，再给出体检数字。

用法： python video/voice_samples.py
产物： out/voice-samples/*.wav
"""
from __future__ import annotations

import asyncio
import pathlib
import shutil
import subprocess
import sys
import wave

import numpy as np

import voice_lab

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "out" / "voice-samples"
RAW = ROOT / "build" / "_vsamp"
LINE = "同一套几何换成节点，就是世界式。七光、四影、两界间、一天理——十四。"

EDGE = [
    ("P1_edge_xiao_08_0", "zh-CN-XiaoxiaoNeural", "+8%", "+0Hz", "本版：edge 女声 +8% / 0Hz + 广播链"),
    ("P2_edge_xiao_12_0", "zh-CN-XiaoxiaoNeural", "+12%", "+0Hz", "更快的 edge 女声 + 广播链"),
    ("P3_edge_yunyang_06", "zh-CN-YunyangNeural", "+6%", "+0Hz", "男声新闻腔 + 广播链（要男声选它）"),
]
MELO = [
    (1.15, "P4_melo_115"),
]


def ffmpeg_exe() -> str:
    return voice_lab.ffmpeg_exe()


async def edge_one(name, voice, rate, pitch) -> pathlib.Path:
    import edge_tts
    mp3 = RAW / f"{name}.mp3"
    await edge_tts.Communicate(LINE, voice=voice, rate=rate, pitch=pitch).save(str(mp3))
    wav = RAW / f"{name}.raw.wav"
    subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-i", str(mp3), "-ar", "48000", "-ac", "1",
                    "-c:a", "pcm_s16le", str(wav)], check=True)
    mp3.unlink(missing_ok=True)
    return wav


def melo_one(speed, name) -> pathlib.Path:
    py = shutil.which("py") or "py"
    script = RAW / "_m.py"
    script.write_text(
        "import sys\nfrom melo.api import TTS\n"
        f"text = {LINE!r}\n"
        "m = TTS(language='ZH', device='cuda:0')\n"
        "spk = m.hps.data.spk2id['ZH']\n"
        f"m.tts_to_file(text, spk, sys.argv[1], speed={speed})\nprint('ok')\n",
        encoding="utf-8",
    )
    out = RAW / f"{name}.raw.wav"
    subprocess.run([py, "-3.11", str(script), str(out)], check=True)
    script.unlink(missing_ok=True)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    jobs = []
    for name, voice, rate, pitch, note in EDGE:
        raw = asyncio.run(edge_one(name, voice, rate, pitch))
        jobs.append((name, raw, note))
    for speed, name in MELO:
        try:
            raw = melo_one(speed, name)
            jobs.append((name, raw, f"MeloTTS {speed} + 广播链（对照：旧引擎）"))
        except Exception as e:  # noqa: BLE001
            print("melo sample skipped:", e)

    rows = {}
    for name, raw, note in jobs:
        polished = OUT / f"{name}.wav"
        voice_lab.polish(raw, polished, quiet=True)
        raw.unlink(missing_ok=True)
        rows[name] = {"note": note}
    stats = voice_lab.review([OUT / f"{n}.wav" for n, _, _ in jobs])
    for name, _, note in jobs:
        s = stats.get(f"{name}.wav", {})
        print(f"  {name:<20} {s.get('dur')}s  f0_std {s.get('f0_std')}  rms_std {s.get('rms_std_db')}dB  | {note}")
    print("samples ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
