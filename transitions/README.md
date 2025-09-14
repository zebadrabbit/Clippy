# transitions

Place transition and bumper videos used between clips.

Expected files (customize as you like):

- intro.mp4   (optional)
- static.mp4  (REQUIRED; used between clips)
- outro.mp4   (optional)

The pipeline references these by relative path from the cache directory.

Normalization & audio policy:
- On first use, assets are normalized into `cache/_trans` as H.264 + AAC 48 kHz stereo for stable concatenation.
- Audio is ON by default for intro/static/transitions/outro. You can silence specific groups in `clippy.yaml` under `audio`.
- If an asset lacks audio, clean stereo audio is synthesized to avoid concat errors.

Resolution order for transitions directory:
1) `TRANSITIONS_DIR` environment variable (absolute or relative)
2) Packaged internal data when `CLIPPY_USE_INTERNAL=1`
3) Standard locations next to the executable or repository (e.g., `./transitions`, `./_internal/transitions`)

Tips:
- `static.mp4` is required; the pipeline inserts it between every clip.
- You can include multiple intros/outros/transitions (e.g., `intro_2.mp4`, `transition_05.mp4`); the pipeline picks randomly where appropriate.
