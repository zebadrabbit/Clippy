from config import *  # noqa: F401,F403

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
        import config as _cfg  # type: ignore
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
        if is_styled:
            body = rendered
        else:
            try:
                body = _style_label_value(rendered) if THEME else chalk.gray(rendered)
            except Exception:
                body = chalk.gray(rendered)
        body = _accent_symbols(body)
        # Use a cross to avoid Markdown heading ("# ")
        try:
            x = THEME.symbol("✖") if THEME else chalk.magenta_bright("✖")
        except Exception:
            x = chalk.magenta_bright("✖")
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
    _font = _fontfile.replace('\\\\', '/').replace('\\\\', '/') if isinstance(_fontfile, str) else _fontfile
    s = s.replace('{fontfile}', _font)
    s = s.replace('{bitrate}', _cfg_get('bitrate', ''))
    s = s.replace('{audio_bitrate}', _cfg_get('audio_bitrate', ''))
    s = s.replace('{fps}', _cfg_get('fps', ''))
    s = s.replace('{resolution}', _cfg_get('resolution', ''))
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

def resolve_transitions_dir() -> str:
    """Resolve the absolute transitions directory.

    Order of preference:
    - TRANSITIONS_DIR env var (absolute or relative to CWD)
    - If CLIPPY_USE_INTERNAL=1, prefer bundled/internal locations first
    - config.transitions_dir if defined
    - PyInstaller MEIPASS (onefile temp dir): <MEIPASS>/transitions, <MEIPASS>/_internal/transitions
    - Next to the executable when frozen: <exe>/transitions, <exe>/_internal/transitions
    - Project source locations: <repo>/transitions, <repo>/_internal/transitions
    - Working directory variants: ./transitions, ./_internal/transitions
    Returns an absolute path; if none exist, returns ./transitions (absolute) as default.
    """
    candidates: list[str] = []
    # Env
    env_dir = os.getenv('TRANSITIONS_DIR')
    if env_dir:
        candidates.append(os.path.abspath(env_dir))
    use_internal = os.getenv('CLIPPY_USE_INTERNAL', '').strip().lower() in ('1', 'true', 'yes', 'on')
    # Config-specified dir (optional)
    try:
        import config as _cfg  # type: ignore
        cfg_dir = getattr(_cfg, 'transitions_dir', None)
        if cfg_dir:
            candidates.append(os.path.abspath(str(cfg_dir)))
    except Exception:
        pass
    # PyInstaller MEIPASS (onefile extracts here)
    try:
        meipass = getattr(sys, '_MEIPASS', None)
    except Exception:
        meipass = None
    if meipass:
        if use_internal:
            candidates.insert(0, os.path.join(meipass, '_internal', 'transitions'))
            candidates.insert(1, os.path.join(meipass, 'transitions'))
        else:
            candidates.append(os.path.join(meipass, 'transitions'))
            candidates.append(os.path.join(meipass, '_internal', 'transitions'))
    # Frozen bundle locations
    try:
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            if use_internal:
                candidates.insert(0, os.path.join(exe_dir, '_internal', 'transitions'))
                candidates.insert(1, os.path.join(exe_dir, 'transitions'))
            else:
                candidates.append(os.path.join(exe_dir, 'transitions'))
                candidates.append(os.path.join(exe_dir, '_internal', 'transitions'))
    except Exception:
        pass
    # Source tree locations
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        if use_internal:
            candidates.append(os.path.join(repo_dir, '_internal', 'transitions'))
            candidates.append(os.path.join(repo_dir, 'transitions'))
        else:
            candidates.append(os.path.join(repo_dir, 'transitions'))
            candidates.append(os.path.join(repo_dir, '_internal', 'transitions'))
    except Exception:
        pass
    # Working dir variants
    try:
        cwd = os.getcwd()
        if use_internal:
            candidates.append(os.path.join(cwd, '_internal', 'transitions'))
            candidates.append(os.path.join(cwd, 'transitions'))
        else:
            candidates.append(os.path.join(cwd, 'transitions'))
            candidates.append(os.path.join(cwd, '_internal', 'transitions'))
    except Exception:
        pass
    for p in candidates:
        try:
            if p and os.path.isdir(p):
                return os.path.abspath(p)
        except Exception:
            continue
    # Fallback to ./transitions absolute
    try:
        return os.path.abspath(os.path.join(os.getcwd(), 'transitions'))
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
            import config as _cfg  # type: ignore
            cfg_dir = getattr(_cfg, 'transitions_dir', None)
            if cfg_dir:
                candidates.append(os.path.abspath(str(cfg_dir)))
        except Exception:
            pass
        # PyInstaller temp and frozen exe dirs
        try:
            meipass = getattr(sys, '_MEIPASS', None)
        except Exception:
            meipass = None
        def _add_pair(base: str):
            if use_internal:
                candidates.append(os.path.join(base, '_internal', 'transitions'))
                candidates.append(os.path.join(base, 'transitions'))
            else:
                candidates.append(os.path.join(base, 'transitions'))
                candidates.append(os.path.join(base, '_internal', 'transitions'))
        if meipass:
            _add_pair(meipass)
        try:
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
                _add_pair(exe_dir)
        except Exception:
            pass
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
        # Normalize slashes for the host OS in logs only
        if os.name == 'nt':
            return p.replace('/', '\\')
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
        "- Compilation concat list files (compN) are written here.\n"
        "- Safe to delete; it will be recreated on next run unless --keep-cache is used.\n"
    ))

    # output dir
    _output = _cfg_get('output', './output')
    _ensure_dir(_output, 'output')
    _ensure_readme(_output, (
        "# output\n\n"
        "Final compilations are moved here after encoding.\n\n"
        "- Filenames include the broadcaster and date range.\n"
        "- Share or upload these files; contents here are not required for future runs.\n"
    ))

    # transitions dir (resolved dynamically)
    transitions_dir = resolve_transitions_dir()
    if not os.path.exists(transitions_dir):
        _ensure_dir(transitions_dir, 'transitions')
    _ensure_readme(transitions_dir, (
        "# transitions\n\n"
        "Put your intro/outro/transition clips here.\n\n"
        "Rules: static.mp4 is REQUIRED and is placed between every segment.\n"
        "You can provide multiple intros/outros/transitions (e.g., intro_2.mp4, transition_05.mp4);\n"
        "the app randomly picks intros/outros and may insert random transitions between clips.\n\n"
        "Examples:\n"
        "- intro.mp4, intro_2.mp4 (optional, random one chosen)\n"
        "- static.mp4  (required)\n"
        "- transition_01.mp4 ... transition_10.mp4 (optional random inserts)\n"
        "- outro.mp4, outro_2.mp4 (optional, random one chosen)\n\n"
        "Files are referenced relative to the cache directory using ffmpeg concat.\n"
    ))

    # Require transitions/static.mp4 to be present; do not auto-create or copy
    try:
        static_path = os.path.join(transitions_dir, 'static.mp4')
        if not os.path.exists(static_path):
            log('WARN transitions/static.mp4 not found. Place your transition clip in the transitions folder.', 1)
    except Exception as e:
        log("Static file check error: " + str(e), 5)
