# Promotional video

`chock-promo.mp4` — the 75-second launch promo (1280x720, narrated). Fully generated
from source in this folder; no screen recording involved.

- `promo.html` + `promo_*.js` — the animation. A single canvas, drawn as a pure function of time:
  `window.seek(t)` renders the exact frame at `t` seconds, so output is deterministic.
  Open it in a browser and press Space to preview.
- `render_frames.py` — renders every frame through headless Chromium
  (`python render_frames.py full 30`, or `test` for one still per scene,
  or `range <t0> <t1>` to re-render a slice after an edit).
- `gen_audio.py` — builds the soundtrack: Edge neural TTS narration, a synthesized
  music bed, and SFX, mixed to `audio.wav`. Requires network for the TTS.
- `gen_captions.py` — derives `chock-promo.srt` from the same narration table, so
  captions never drift from the audio. Feeds autoplay-muted platforms (LinkedIn, X).

Assemble — no system ffmpeg needed; `imageio-ffmpeg` bundles a binary (it is *not* on
`PATH`; the last line resolves its real location):

```bash
pip install playwright edge-tts numpy imageio-ffmpeg
python -m playwright install chromium
python render_frames.py full 30
python gen_audio.py
"$(python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" \
  -framerate 30 -i frames/f%05d.png -i audio.wav \
  -c:v libx264 -pix_fmt yuv420p -crf 18 -c:a aac -shortest chock-promo.mp4
```

Editing narration text or the voice? Delete `audio_work/` first — the TTS cache is
keyed by line index only, so a stale clip is otherwise reused silently.

Content rules, same as everywhere in this repo: the terminal output shown in the
video is real captured output — regenerate it from a real run if a message changes,
and keep policy **counts** out of the script and visuals so the video cannot go stale
as the catalog grows.
