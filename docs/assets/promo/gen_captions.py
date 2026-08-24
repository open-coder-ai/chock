"""Generate chock-promo.srt from the narration table in gen_audio.py.

LinkedIn (and most feeds) autoplay muted, so the narration only reaches viewers as
captions. Deriving the SRT from NARRATION keeps the two from drifting: edit the
narration, re-run this, re-upload.
"""

from pathlib import Path

from gen_audio import NARRATION

#: Rough speaking rate used to size each caption window; the TTS runs at a similar
#: pace and the next line's start time caps the window anyway.
SECONDS_PER_WORD = 0.36
GAP = 0.25


def _ts(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02}:{int(m):02}:{int(s):02},{int((s % 1) * 1000):03}"


def main() -> None:
    lines = []
    for i, (start, text) in enumerate(NARRATION):
        text = " ".join(text.split()).replace("C I ", "CI ").replace("V S Code", "VS Code")
        est_end = start + len(text.split()) * SECONDS_PER_WORD
        next_start = NARRATION[i + 1][0] if i + 1 < len(NARRATION) else est_end + 2
        end = min(est_end, next_start - GAP)
        lines += [str(i + 1), f"{_ts(start)} --> {_ts(end)}", text, ""]
    out = Path(__file__).parent / "chock-promo.srt"
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {out.name}: {len(NARRATION)} captions")


if __name__ == "__main__":
    main()
