"""Build the full 75s audio track: neural TTS narration + synth music bed + SFX.

Outputs audio.wav (48kHz stereo) ready to mux with the video.
"""

import asyncio
import subprocess
import wave
from pathlib import Path

import edge_tts
import imageio_ffmpeg
import numpy as np

HERE = Path(__file__).parent
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
SR = 48000
TOTAL = 75.0

VOICE = "en-US-AndrewMultilingualNeural"

# (start_seconds, text)
NARRATION = [
    (
        0.8,
        "Open source has a new problem. Contributors' AI agents can write ten "
        "pull requests in a weekend — and you are still one human reading diffs.",
    ),
    (
        12.5,
        "Chock is governance as code. Write a policy once, commit it — and your rules travel with every fork.",
    ),
    (
        22.5,
        "The compiler turns it into the strongest control every agent supports. "
        "Git hooks. C I gates. Native hooks in Claude Code, Cursor, Copilot, and V S Code. "
        "Across fourteen agents.",
    ),
    (
        34.8,
        "So when a contributor's agent stages a credential — on their machine — it is blocked before the pull request exists.",
    ),
    (42.5, "What reaches you has already passed your gates — and your C I gate backs it up."),
    (
        48.5,
        "Every policy carries an eval suite, and a coverage report that tells you "
        "exactly where a guarantee holds — and where it doesn't.",
    ),
    (
        58.5,
        "A growing catalog of ready policies, including coverage of the full "
        "OWASP agentic security top ten — with its limits stated honestly.",
    ),
    (69.0, "Chock. Govern the agent. Review the policy once — not every pull request."),
]


async def tts_line(text: str, path: Path) -> None:
    await edge_tts.Communicate(text, VOICE, rate="+4%").save(str(path))


def mp3_to_array(path: Path) -> np.ndarray:
    """Decode any audio file to float32 mono @ SR using ffmpeg."""
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


# ---------------- music bed ----------------
def note(freq: float, dur: float, vol: float = 1.0) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    # two detuned saw-ish oscillators, softened
    s = (
        np.sin(2 * np.pi * freq * t) * 0.6
        + np.sin(2 * np.pi * freq * 1.004 * t) * 0.4
        + np.sin(2 * np.pi * freq * 0.5 * t) * 0.5
    )
    # slow attack/release envelope
    n = len(t)
    env = np.minimum(np.arange(n) / (SR * 0.8), 1.0) * np.minimum((n - np.arange(n)) / (SR * 1.2), 1.0)
    return (s * np.clip(env, 0, 1) * vol).astype(np.float32)


def lowpass(x: np.ndarray, alpha: float = 0.015) -> np.ndarray:
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += alpha * (x[i] - acc)
        y[i] = acc
    return y


def music_bed() -> np.ndarray:
    out = np.zeros(int(TOTAL * SR), dtype=np.float32)
    # Am – F – C – G progression, 7.5s per chord, ambient
    chords = [
        [110.0, 164.81, 220.0],  # A2 E3 A3
        [87.31, 174.61, 261.63],  # F2 F3 C4
        [130.81, 196.0, 261.63],  # C3 G3 C4
        [98.0, 196.0, 246.94],  # G2 G3 B3
    ]
    seg_d = 7.5
    for i in range(int(TOTAL / seg_d) + 1):
        chord = chords[i % 4]
        start = int(i * seg_d * SR)
        for f in chord:
            nt = note(f, seg_d + 1.5, 0.16)
            end = min(start + len(nt), len(out))
            out[start:end] += nt[: end - start]
    out = lowpass(out, 0.02)
    # gentle fade in/out for the whole bed
    fade = int(1.5 * SR)
    out[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    out[-int(4 * SR) :] *= np.linspace(1, 0, int(4 * SR), dtype=np.float32)
    return out


def sfx_buzz(dur: float = 0.5) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    s = np.sign(np.sin(2 * np.pi * 55 * t)) * 0.5 + np.sin(2 * np.pi * 58 * t) * 0.5
    env = np.exp(-t * 6)
    return (s * env * 0.30).astype(np.float32)


def sfx_chime() -> np.ndarray:
    t = np.arange(int(1.2 * SR)) / SR
    s = np.sin(2 * np.pi * 880 * t) + 0.5 * np.sin(2 * np.pi * 1318.5 * t) + 0.3 * np.sin(2 * np.pi * 1760 * t)
    env = np.exp(-t * 4)
    return (s * env * 0.16).astype(np.float32)


def sfx_whoosh() -> np.ndarray:
    rng = np.random.default_rng(7)
    t = np.arange(int(0.6 * SR)) / SR
    noise = rng.standard_normal(len(t)).astype(np.float32)
    noise = lowpass(noise, 0.05)
    env = np.sin(np.pi * t / 0.6) ** 2
    return (noise * env * 0.10).astype(np.float32)


def place(track: np.ndarray, clip: np.ndarray, at: float) -> None:
    i = int(at * SR)
    end = min(i + len(clip), len(track))
    if i < len(track):
        track[i:end] += clip[: end - i]


async def main() -> None:
    work = HERE / "audio_work"
    work.mkdir(exist_ok=True)

    # 1. narration
    print("TTS narration…", flush=True)
    for i, (_, line) in enumerate(NARRATION):
        p = work / f"narr{i}.mp3"
        if not p.exists():
            await tts_line(line, p)
            print(f"  line {i} done", flush=True)

    track = music_bed()
    print("music bed done", flush=True)

    for i, (at, _) in enumerate(NARRATION):
        arr = mp3_to_array(work / f"narr{i}.mp3")
        # duck the music under this line
        s, e = int(at * SR), min(int(at * SR) + len(arr) + int(0.3 * SR), len(track))
        track[s:e] *= 0.45
        place(track, arr * 0.9, at)
        print(f"  narration {i}: {len(arr) / SR:.1f}s at {at}s", flush=True)

    # 2. SFX — timed to the animation
    place(track, sfx_buzz(), 37.4)  # the blocked commit lands (scene4 lt=3.4)
    place(track, sfx_chime(), 44.6)  # [PASS] appears (scene4 lt=10.6)
    for t0 in (12.0, 22.0, 34.0, 48.0, 58.0, 68.0):  # scene transitions
        place(track, sfx_whoosh(), t0 - 0.3)

    # 3. master: soft clip + write wav
    track = np.tanh(track * 1.1) * 0.9
    stereo = np.repeat(track[:, None], 2, axis=1)
    pcm = (np.clip(stereo, -1, 1) * 32767).astype(np.int16)
    out = HERE / "audio.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"wrote {out} ({TOTAL}s)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
