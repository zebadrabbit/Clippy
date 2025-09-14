# transitions

Place transition and bumper videos used between clips.

Expected files (customize as you like):

- intro.mp4   (optional)
- static.mp4  (REQUIRED; used between clips)
- outro.mp4   (optional)

The pipeline references these by relative path from the cache directory.

Audio policy:
- Audio is kept ON by default for intro/static/transitions/outro.
- On first use, assets are normalized into `cache/_trans` as H.264 + AAC 48 kHz stereo for stable concatenation.
- If an asset lacks audio, clean stereo audio is synthesized to avoid concat errors.
