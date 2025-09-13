from config import *  # noqa: F401,F403

from yachalk import chalk
import re, os, sys, subprocess, shutil

# Simple opt-in color/style tags using '{@tag}', e.g.
# "{@blue}this is blue {@green}now green {@reset}back to default".
_TAG_RX = re.compile(r"\{@([A-Za-z][A-Za-z0-9]*)\}")

_COLOR_ATTRS = {
    # standard colors
    "black": "black",
    "red": "red",
    "green": "green",
    "yellow": "yellow",
    "blue": "blue",
    "magenta": "magenta",
    "cyan": "cyan",
    "white": "white",
    "gray": "gray",
    "grey": "gray",
    # bright variants (yachalk uses snake_case names)
    "blackbright": "black_bright",
    "redbright": "red_bright",
    "greenbright": "green_bright",
    "yellowbright": "yellow_bright",
    "bluebright": "blue_bright",
    "magentabright": "magenta_bright",
    "cyanbright": "cyan_bright",
    "whitebright": "white_bright",
}

_STYLE_ATTRS = {
    "bold": "bold",
    "dim": "dim",
    "italic": "italic",
    "underline": "underline",
    "inverse": "inverse",
    "strikethrough": "strikethrough",
}


def _build_styler(active_colors: list[str], active_styles: list[str]):
    # If no styles/colors are active, return identity to avoid calling ChalkFactory
    if not active_colors and not active_styles:
        return lambda txt: txt
    s = chalk
    for name in active_colors + active_styles:
        s = getattr(s, name)
    return lambda txt: str(s(txt))


def _apply_color_tags(text: str) -> tuple[str, bool]:
    """Render text with {color}/{style}/{reset} tags using yachalk.

    Returns (rendered_text, used_known_tags).
    Unknown tags are left verbatim (e.g. {cache}). Only '{@...}' are parsed.
    """
    if not text or "{" not in text:
        return text, False
    out: list[str] = []
    idx = 0
    active_color: list[str] = []  # at most 1 color kept
    active_styles: list[str] = []
    used = False

    for m in _TAG_RX.finditer(text):
        tag = m.group(1)
        start, end = m.span()
        # preceding literal segment
        segment = text[idx:start]
        if segment:
            styler = _build_styler(active_color, active_styles)
            out.append(styler(segment))
        idx = end

        low = tag.lower()
        if low == "reset":
            active_color.clear()
            active_styles.clear()
            used = True
            continue
        # color?
        color_attr = _COLOR_ATTRS.get(low)
        if color_attr:
            active_color[:] = [color_attr]
            used = True
            continue
        # style?
        style_attr = _STYLE_ATTRS.get(low)
        if style_attr:
            if style_attr not in active_styles:
                active_styles.append(style_attr)
            used = True
            continue
        # unknown tag: keep literal braces
        out.append("{" + tag + "}")

    # trailing remainder
    if idx < len(text):
        styler = _build_styler(active_color, active_styles)
        out.append(styler(text[idx:]))
    return "".join(out), used

def log(msg, level=0):
    """Structured log with colorized levels.

    Levels:
      0 info, 1 action, 2 stage, 5 error
    """
    raw = str(msg)
    rendered, used_tags = _apply_color_tags(raw)
    if level == 0:
        body = rendered if used_tags else chalk.gray(raw)
        out = "  " + body
    elif level == 1:
        body = rendered if used_tags else chalk.gray(raw)
        out = chalk.green("-") + " " + body
    elif level == 2:
        body = rendered if used_tags else chalk.gray(raw)
        out = chalk.blue(">") + " " + body
    elif level == 5:
        body = rendered if used_tags else chalk.gray(raw)
        out = chalk.red("#") + " " + body
    else:
        body = rendered if used_tags else chalk.gray(raw)
        out = body
    print(out)

# sanitize non-ASCII to a safe subset for overlays/filenames
def fix_ascii(s: str) -> str:
    return re.sub(r'[^A-Za-z0-9 ]+', '', str(s))

# convert variables in the config to actual values
def replace_vars(s, m):
    s = s.replace('{cache}', cache)
    s = s.replace('{message_id}', str(m[0]))
    # Escape single quotes for ffmpeg drawtext text argument
    author = (m[2] or '').replace("'", "\\'")
    s = s.replace('{author}', author)
    # Normalize font path to forward slashes for ffmpeg on Windows
    _font = fontfile.replace('\\\\', '/').replace('\\\\', '/') if isinstance(fontfile, str) else fontfile
    s = s.replace('{fontfile}', _font)
    s = s.replace('{bitrate}', bitrate)
    s = s.replace('{audio_bitrate}', audio_bitrate)
    s = s.replace('{fps}', fps)
    s = s.replace('{resolution}', resolution)
    # yt-dlp format string
    try:
        from config import yt_format
        s = s.replace('{yt_format}', yt_format)
    except Exception:
        pass
    # ffmpeg path for yt-dlp --ffmpeg-location
    try:
        from config import ffmpeg as _ff
        s = s.replace('{ffmpeg_path}', _ff)
    except Exception:
        pass
    # NVENC tuning placeholders (if defined)
    try:
        from config import cq, gop, rc_lookahead, spatial_aq, temporal_aq, aq_strength, nvenc_preset
        s = s.replace('{cq}', cq)
        s = s.replace('{gop}', gop)
        s = s.replace('{rc_lookahead}', rc_lookahead)
        s = s.replace('{spatial_aq}', spatial_aq)
        s = s.replace('{temporal_aq}', temporal_aq)
        s = s.replace('{aq_strength}', aq_strength)
        s = s.replace('{nvenc_preset}', nvenc_preset)
    except Exception:
        pass
    # optional container parameters
    try:
        from config import container_ext, container_flags
        s = s.replace('{ext}', container_ext)
        s = s.replace('{container_flags}', container_flags)
    except Exception:
        pass
    return s

# clean up the cache folders and get ready to do some work
def prep_work():
    # make our workspace
    def _display_path(p: str) -> str:
        # Normalize slashes for the host OS in logs only
        if os.name == 'nt':
            return p.replace('/', '\\')
        return p

    def _ensure_dir(path: str, label: str):
        try:
            if not os.path.exists(path):
                log(f"{{@green}}creating new{{@reset}} {{@white}}{label}{{@reset}} {{@green}}directory at{{@reset}} {{@cyan}}" + _display_path(path), 1)
                os.makedirs(path, exist_ok=True)
        except Exception as e:
            log("{@redbright}{@bold}Failed to create " + str(label) + " dir:{@reset} {@white}" + str(e), 5)

    def _ensure_readme(path: str, content: str):
        try:
            readme_path = os.path.join(path, 'README.md')
            if not os.path.exists(readme_path):
                with open(readme_path, 'w', encoding='utf-8') as f:
                    f.write(content)
        except Exception as e:
            log("{@redbright}{@bold}Failed to write README in " + str(path) + ":{@reset} {@white}" + str(e), 5)

    # cache dir
    _ensure_dir(cache, 'cache')
    _ensure_readme(cache, (
        "# cache\n\n"
        "Temporary working directory.\n\n"
        "- Each clip gets its own subfolder with intermediate files (clip.mp4, normalized.mp4, preview.png).\n"
        "- Compilation concat list files (compN) are written here.\n"
        "- Safe to delete; it will be recreated on next run unless --keep-cache is used.\n"
    ))

    # output dir
    _ensure_dir(output, 'output')
    _ensure_readme(output, (
        "# output\n\n"
        "Final compilations are moved here after encoding.\n\n"
        "- Filenames include the broadcaster and date range.\n"
        "- Share or upload these files; contents here are not required for future runs.\n"
    ))

    # transitions dir (sibling of working dir)
    transitions_dir = os.path.join('.', 'transitions')
    _ensure_dir(transitions_dir, 'transitions')
    _ensure_readme(transitions_dir, (
        "# transitions\n\n"
        "Place transition and bumper videos used between clips.\n\n"
        "Expected files (customize as you like):\n\n"
        "- intro.mp4   (optional)\n"
        "- static.mp4  (used between clips)\n"
        "- outro.mp4   (optional)\n\n"
        "The pipeline references these by relative path from the cache directory.\n"
    ))

    # Ensure we use the real transitions/static.mp4 if available; only create a placeholder as a last resort
    try:
        static_name = 'static.mp4'
        static_path = os.path.join(transitions_dir, static_name)
        # Candidate source transitions directory (prefer next to executable when frozen; else repo path)
        try:
            if getattr(sys, 'frozen', False):
                src_transitions = os.path.join(os.path.dirname(sys.executable), 'transitions')
            else:
                src_transitions = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'transitions')
        except Exception:
            src_transitions = None

        # If a real static.mp4 exists at the source and it's different or missing at destination, copy it
        if src_transitions:
            src_static = os.path.join(src_transitions, static_name)
            if os.path.exists(src_static) and not os.path.exists(static_path):
                try:
                    shutil.copy2(src_static, static_path)
                    log('{@blue}Copied transitions/static.mp4 from source', 2)
                except Exception as _e:
                    log("{@yellow}{@bold}WARN{@reset} Could not copy transitions/static.mp4 from source: {@white}" + str(_e), 2)

        # If still missing, create a tiny placeholder
        if not os.path.exists(static_path):
            log('{@green}Creating default transitions/static.mp4 placeholder', 1)
            cmd = (
                ffmpeg + ' -y -f lavfi -i "color=c=black:s=' + str(resolution) + ':r=' + str(fps) + ':d=1" '
                '-c:v libx264 -pix_fmt yuv420p -movflags +faststart "' + static_path + '"'
            )
            try:
                subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            except Exception:
                pass
            if os.path.exists(static_path):
                log('{@blue}Created placeholder static.mp4', 2)
            else:
                log('{@redbright}{@bold}Could not create placeholder static.mp4. Ensure ffmpeg is available.', 5)
    except Exception as e:
        log("{@redbright}{@bold}Static placeholder creation error:{@reset} {@white}" + str(e), 5)
