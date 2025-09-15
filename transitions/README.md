# transitions

Place transition and bumper videos used between clips.

Expected files (customize as you like):

- intro.mp4   (optional)
- static.mp4  (REQUIRED; used between clips)
- outro.mp4   (optional)

The pipeline references these by relative path from the cache directory.

Normalization & audio policy:
- On first use, assets are normalized into `cache/_trans` as H.264 + AAC 48 kHz stereo for stable concatenation.
- Audio is ON by default for all assets. You may silence only `static.mp4` via `audio.silence_static` in `clippy.yaml`.
- If an asset lacks audio, clean stereo audio is synthesized to avoid concat errors.

Resolution order for transitions directory:
1) `TRANSITIONS_DIR` environment variable (absolute or relative)
2) `transitions_dir` in `clippy.yaml` (if set)
3) Repository `./transitions` or current working directory `./transitions`

Tips:
- `static.mp4` is required; the pipeline inserts it between every clip.
- You can include multiple intros/outros/transitions (e.g., `intro_2.mp4`, `transition_05.mp4`); the pipeline picks randomly where appropriate.
