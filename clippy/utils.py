from clippy.config import *  # noqa: F401,F403

from yachalk import chalk
try:
    from clippy.theme import THEME, enable_windows_vt  # type: ignore
except Exception:  # pragma: no cover
    THEME = None  # type: ignore
    def enable_windows_vt():  # type: ignore
        return
import re, os, sys, subprocess

# Note: Legacy '{@tag}' color markers were removed. Styling is applied centrally via THEME.


def _cfg_get(name: str, default=None):
    """Best-effort getter for config values without relying on star-import globals.

    Tries module-level global first (set by main at runtime), then config module attribute.
    """
    try:
        if name in globals():
            return globals()[name]
    except Exception:
        pass
    try:
        import clippy.config as _cfg  # type: ignore
        return getattr(_cfg, name)
    except Exception:
        return default


def _accent_symbols(s: str) -> str:
    """Apply symbol accent color to common standalone symbols.

    Light heuristic: arrows, simple arrow token, middle colons, asterisks.
    """
    try:
        sym = THEME.symbol  # may raise if THEME missing
    except Exception:
        return s
    try:
        # Arrow token '->' becomes a single accented arrow
        s = s.replace(" -> ", " " + str(sym("→")) + " ")
        # Existing arrow glyphs
        s = s.replace("→", str(sym("→")))
        # Colons between label and value: ' : '
        s = s.replace(" : ", " " + str(sym(":")) + " ")
        # Asterisks surrounded by spaces
        s = s.replace(" * ", " " + str(sym("*")) + " ")
        return s
    except Exception:
        return s

def _looks_like_path(val: str) -> bool:
    try:
        if not val:
            return False
        v = val.strip()
        # Windows drive letter or contains path separators
        if len(v) >= 3 and v[1] == ':' and (v[2] == '\\' or v[2] == '/'):
            return True
        if ('/' in v) or ('\\' in v):
            return True
        # common file-ish values
        if any(v.lower().endswith(ext) for ext in ('.mp4', '.mp3', '.wav', '.png', '.jpg', '.jpeg', '.json', '.txt')):
            return True
        return False
    except Exception:
        return False

def _style_label_value(rendered: str) -> str:
    """Apply theme to 'Label: Value' patterns: label in label/section color, value in value/path color.

    Falls back to THEME.text when heuristics don't match or THEME is unavailable.
    """
    try:
        if THEME is None:
            return chalk.gray(rendered)
    except Exception:
        return chalk.gray(rendered)
    try:
        if ': ' not in rendered:
            # No obvious label/value split; default styling
            return THEME.text(rendered)
        label, value = rendered.split(': ', 1)
        # Choose styles
        try:
            label_fn = getattr(THEME, 'label', None) or getattr(THEME, 'section', None) or THEME.text
        except Exception:
            label_fn = THEME.text
        try:
            value_fn = getattr(THEME, 'value', None) or THEME.text
        except Exception:
            value_fn = THEME.text
        try:
            path_fn = getattr(THEME, 'path', None) or value_fn
        except Exception:
            path_fn = value_fn
        # Compose with a themed separator if available
        try:
            sep = str(THEME.symbol(':'))
        except Exception:
            sep = ':'
        right = (path_fn if _looks_like_path(value) else value_fn)(value)
        return f"{label_fn(label)} {sep} {right}"
    except Exception:
        # best-effort fallback
        try:
            return THEME.text(rendered)
        except Exception:
            return rendered

def log(msg, level=0):
    """Structured log with colorized levels.

    Levels:
      0 info, 1 action, 2 stage, 5 error
    """
    # Ensure Windows consoles render ANSI colors
    try:
        enable_windows_vt()
    except Exception:
        pass
    rendered = str(msg)
    # If message already contains ANSI codes, treat it as pre-styled and don't recolor
    is_styled = "\x1b[" in rendered
    if level == 0:
        if is_styled:
            body = rendered
        else:
            try:
                body = _style_label_value(rendered) if THEME else chalk.gray(rendered)
            except Exception:
                body = chalk.gray(rendered)
        body = _accent_symbols(body)
        out = "  " + body
    elif level == 1:
        if is_styled:
            body = rendered
        else:
            try:
                body = _style_label_value(rendered) if THEME else chalk.gray(rendered)
            except Exception:
                body = chalk.gray(rendered)
        body = _accent_symbols(body)
        # Use a bullet to avoid Markdown list trigger ("- ")
        try:
            bullet = THEME.symbol("•") if THEME else chalk.magenta_bright("•")
        except Exception:
            bullet = chalk.magenta_bright("•")
        out = bullet + " " + body
    elif level == 2:
        if is_styled:
            body = rendered
        else:
            try:
                body = _style_label_value(rendered) if THEME else chalk.gray(rendered)
            except Exception:
                body = chalk.gray(rendered)
        body = _accent_symbols(body)
        # Use a chevron to avoid Markdown blockquote ("> ")
        try:
            chev = THEME.symbol("›") if THEME else chalk.magenta_bright("›")
        except Exception:
            chev = chalk.magenta_bright("›")
        out = chev + " " + body
    elif level == 5:
        # Errors: render in bright red, including the leading symbol
        if is_styled:
            body = rendered
        else:
            try:
                raw = _style_label_value(rendered) if THEME else rendered
            except Exception:
                raw = rendered
            try:
                body = THEME.error(raw) if THEME else chalk.red_bright(raw)
            except Exception:
                body = chalk.red_bright(raw)
        try:
            x = THEME.error("✖") if THEME else chalk.red_bright("✖")
        except Exception:
            x = chalk.red_bright("✖")
        out = x + " " + body
    else:
        if is_styled:
            body = rendered
        else:
            try:
                body = _style_label_value(rendered) if THEME else chalk.gray(rendered)
            except Exception:
                body = chalk.gray(rendered)
        body = _accent_symbols(body)
        out = body
    print(out)

# sanitize non-ASCII to a safe subset for overlays/filenames
def fix_ascii(s: str) -> str:
    return re.sub(r'[^A-Za-z0-9 ]+', '', str(s))

# convert variables in the config to actual values
def replace_vars(s, m):
    _cache = _cfg_get('cache', '')
    s = s.replace('{cache}', _cache)
    s = s.replace('{message_id}', str(m[0]))
    # Escape single quotes for ffmpeg drawtext text argument
    author = (m[2] or '').replace("'", "\\'")
    s = s.replace('{author}', author)
    # Normalize font path to forward slashes for ffmpeg on Windows
    _fontfile = _cfg_get('fontfile', None)
    _font = _fontfile.replace('\\', '/').replace('\\', '/') if isinstance(_fontfile, str) else _fontfile
    # When used inside filter_complex with single quotes around parameters, keep fontfile quoted
    # The template expects fontfile='{fontfile}' so we only need to inject the raw path here
    s = s.replace('{fontfile}', _font)
    s = s.replace('{bitrate}', _cfg_get('bitrate', ''))
    s = s.replace('{audio_bitrate}', _cfg_get('audio_bitrate', ''))
    s = s.replace('{fps}', _cfg_get('fps', ''))
    s = s.replace('{resolution}', _cfg_get('resolution', ''))
    # Encoder tuning parameters
    s = s.replace('{cq}', _cfg_get('cq', ''))
    s = s.replace('{gop}', _cfg_get('gop', ''))
    s = s.replace('{rc_lookahead}', _cfg_get('rc_lookahead', ''))
    s = s.replace('{spatial_aq}', _cfg_get('spatial_aq', ''))
    s = s.replace('{aq_strength}', _cfg_get('aq_strength', ''))
    s = s.replace('{temporal_aq}', _cfg_get('temporal_aq', ''))
    s = s.replace('{nvenc_preset}', _cfg_get('nvenc_preset', ''))
    # Container settings
    s = s.replace('{ext}', _cfg_get('container_ext', 'mp4'))
    s = s.replace('{container_flags}', _cfg_get('container_flags', '-movflags +faststart'))
    # yt-dlp format string
    try:
        from clippy.config import yt_format
        s = s.replace('{yt_format}', yt_format)
    except Exception:
        pass
    # ffmpeg path into youtubeDl options
    try:
        from clippy.config import ffmpeg as _ff
        s = s.replace('{ffmpeg_path}', _ff)
    except Exception:
        pass
    return s

def resolve_transitions_dir() -> str:
    try:
        env_dir = os.getenv('TRANSITIONS_DIR')
        if env_dir:
            return os.path.abspath(env_dir)
    except Exception:
        pass
    # Respect packaged/internal preference
    prefer_internal = os.getenv('CLIPPY_USE_INTERNAL', '').strip().lower() in ('1', 'true', 'yes', 'on')
    roots: list[str] = []
    try:
        import clippy.config as _cfg  # type: ignore
        cfg_dir = getattr(_cfg, 'transitions_dir', None)
        if cfg_dir:
            roots.append(os.path.abspath(str(cfg_dir)))
    except Exception:
        pass
    # Source roots only: repo and CWD
    # Repo and CWD fallbacks
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        if prefer_internal:
            roots += [os.path.join(repo_dir, '..', '_internal', 'transitions'), os.path.join(repo_dir, '..', 'transitions')]
        else:
            roots += [os.path.join(repo_dir, '..', 'transitions'), os.path.join(repo_dir, '..', '_internal', 'transitions')]
    except Exception:
        pass
    try:
        cwd = os.getcwd()
        if prefer_internal:
            roots += [os.path.join(cwd, '_internal', 'transitions'), os.path.join(cwd, 'transitions')]
        else:
            roots += [os.path.join(cwd, 'transitions'), os.path.join(cwd, '_internal', 'transitions')]
    except Exception:
        pass
    for r in roots:
        try:
            if r and os.path.isdir(r):
                return os.path.abspath(r)
        except Exception:
            continue
    try:
        return os.path.abspath('transitions')
    except Exception:
        return os.path.abspath('transitions')

def find_transition_file(name: str) -> str | None:
    """Find a transition asset by name across all known roots.

    Respects CLIPPY_USE_INTERNAL preference order but will fall back to
    non-internal roots if the file is not present in the preferred location.
    Returns absolute file path if found, else None.
    """
    try:
        if not name:
            return None
        # Absolute path shortcut
        if os.path.isabs(name) and os.path.exists(name):
            return os.path.abspath(name)
        # Build candidate directories in the same order as resolve_transitions_dir,
        # but keep all of them to allow fallback per file.
        candidates: list[str] = []
        env_dir = os.getenv('TRANSITIONS_DIR')
        if env_dir:
            candidates.append(os.path.abspath(env_dir))
        use_internal = os.getenv('CLIPPY_USE_INTERNAL', '').strip().lower() in ('1', 'true', 'yes', 'on')
        # Config-specified dir
        try:
            import clippy.config as _cfg  # type: ignore
            cfg_dir = getattr(_cfg, 'transitions_dir', None)
            if cfg_dir:
                candidates.append(os.path.abspath(str(cfg_dir)))
        except Exception:
            pass
        def _add_pair(base: str):
            if use_internal:
                candidates.append(os.path.join(base, '_internal', 'transitions'))
                candidates.append(os.path.join(base, 'transitions'))
            else:
                candidates.append(os.path.join(base, 'transitions'))
                candidates.append(os.path.join(base, '_internal', 'transitions'))
        try:
            repo_dir = os.path.dirname(os.path.abspath(__file__))
            _add_pair(repo_dir)
        except Exception:
            pass
        try:
            cwd = os.getcwd()
            _add_pair(cwd)
        except Exception:
            pass
        # Now test each candidate
        for root in candidates:
            try:
                p = os.path.join(root, name)
                if os.path.exists(p):
                    return os.path.abspath(p)
            except Exception:
                continue
        return None
    except Exception:
        return None

# clean up the cache folders and get ready to do some work
def prep_work():
    # make our workspace
    def _display_path(p: str) -> str:
        try:
            return os.path.abspath(p)
        except Exception:
            return p
    def _ensure_dir(path: str, label: str):
        try:
            if not os.path.exists(path):
                log(f"creating new {label} directory at " + _display_path(path), 1)
                os.makedirs(path, exist_ok=True)
        except Exception as e:
            log("Failed to create " + str(label) + " dir: " + str(e), 5)

    def _ensure_readme(path: str, content: str):
        try:
            readme_path = os.path.join(path, 'README.md')
            if not os.path.exists(readme_path):
                os.makedirs(path, exist_ok=True)
                with open(readme_path, 'w', encoding='utf-8') as f:
                    f.write(content)
        except Exception as e:
            log("Failed to write README in " + str(path) + ": " + str(e), 5)

    # cache dir
    _cache = _cfg_get('cache', './cache')
    _ensure_dir(_cache, 'cache')
    _ensure_readme(_cache, (
        "# cache\n\n"
        "Temporary working directory.\n\n"
        "- Each clip gets its own subfolder with intermediate files (clip.mp4, normalized.mp4, preview.png).\n"
        "- Stage 2 outputs are written as complete_<date>_<idx>.<ext> before being moved to output/.\n"
    ))

    # output dir
    _output = _cfg_get('output', './output')
    _ensure_dir(_output, 'output')
    _ensure_readme(_output, (
        "# output\n\n"
        "Final compilations are moved here after encoding.\n\n"
        "- Filenames include the broadcaster and date range.\n"
        "- Use --overwrite-output to replace existing files, else _1, _2 suffixes are added.\n"
    ))

    # transitions dir
    transitions_dir = resolve_transitions_dir()
    _ensure_readme(transitions_dir, (
        "# transitions\n\n"
        "Put your intro/outro/transition clips here.\n\n"
        "- static.mp4 is REQUIRED.\n"
        "- You can provide intro_2.mp4, outro_2.mp4, transition_01.mp4, etc.\n"
    ))
    try:
        static_path = os.path.join(transitions_dir, 'static.mp4')
        if not os.path.exists(static_path):
            log('WARN transitions/static.mp4 not found. Place your transition clip in the transitions folder.', 1)
    except Exception as e:
        log("Static file check error: " + str(e), 5)
