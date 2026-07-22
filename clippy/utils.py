from yachalk import chalk

import clippy.config as _cfg_mod

try:
    from clippy.theme import THEME, enable_windows_vt  # type: ignore
except ImportError:  # pragma: no cover
    THEME = None  # type: ignore

    def enable_windows_vt():  # type: ignore
        return


import os
import re

# Note: Legacy '{@tag}' color markers were removed. Styling is applied centrally via THEME.


def _cfg_get(name: str, default=None):
    """Best-effort getter for config values.

    Prefers the typed ``ClippyConfig`` singleton (the single source of truth)
    and falls back to the legacy module globals for values it does not model
    (binary paths, transitions_dir, etc.).
    """
    try:
        flat = _cfg_mod.get_config().to_flat_dict()
        if name in flat:
            return flat[name]
    except Exception:  # typed config unavailable; fall through to globals
        pass
    try:
        return getattr(_cfg_mod, name, default)
    except Exception:  # config can fail in many ways; broad catch intentional
        return default


def _accent_symbols(s: str) -> str:
    """Apply symbol accent color to common standalone symbols.

    Light heuristic: arrows, simple arrow token, middle colons, asterisks.
    """
    try:
        sym = THEME.symbol  # may raise if THEME missing
    except (AttributeError, TypeError):
        return s
    try:
        # Arrow token '->' becomes a single accented arrow
        s = s.replace(" -> ", " " + str(sym("\u2192")) + " ")
        # Existing arrow glyphs
        s = s.replace("\u2192", str(sym("\u2192")))
        # Colons between label and value: ' : '
        s = s.replace(" : ", " " + str(sym(":")) + " ")
        # Asterisks surrounded by spaces
        s = s.replace(" * ", " " + str(sym("*")) + " ")
        return s
    except (AttributeError, TypeError):
        return s


def _looks_like_path(val: str) -> bool:
    try:
        if not val:
            return False
        v = val.strip()
        # Windows drive letter or contains path separators
        if len(v) >= 3 and v[1] == ":" and (v[2] == "\\" or v[2] == "/"):
            return True
        # A real path separator has no whitespace around it ("output/foo.mp4",
        # "C:\Clippy\bin"). A bare "/" or "\" check also matches things like a
        # Discord "Guild Name / #channel" display string, which isn't a path.
        if re.search(r"\S[/\\]\S", v):
            return True
        # common file-ish values
        if any(
            v.lower().endswith(ext)
            for ext in (".mp4", ".mp3", ".wav", ".png", ".jpg", ".jpeg", ".json", ".txt")
        ):
            return True
        return False
    except (AttributeError, TypeError):
        return False


def _style_label_value(rendered: str) -> str:
    """Apply theme to 'Label: Value' patterns: label in label/section color, value in value/path color.

    Falls back to THEME.text when heuristics don't match or THEME is unavailable.
    """
    try:
        if THEME is None:
            return chalk.gray(rendered)
    except (AttributeError, TypeError):
        return chalk.gray(rendered)
    try:
        if ": " not in rendered:
            # No obvious label/value split; default styling
            return THEME.text(rendered)
        label, value = rendered.split(": ", 1)
        # Choose styles
        try:
            label_fn = (
                getattr(THEME, "label", None) or getattr(THEME, "section", None) or THEME.text
            )
        except (AttributeError, TypeError):
            label_fn = THEME.text
        try:
            value_fn = getattr(THEME, "value", None) or THEME.text
        except (AttributeError, TypeError):
            value_fn = THEME.text
        try:
            path_fn = getattr(THEME, "path", None) or value_fn
        except (AttributeError, TypeError):
            path_fn = value_fn
        # Compose with a themed separator if available
        try:
            sep = str(THEME.symbol(":"))
        except (AttributeError, TypeError):
            sep = ":"
        right = (path_fn if _looks_like_path(value) else value_fn)(value)
        return f"{label_fn(label)} {sep} {right}"
    except (AttributeError, TypeError):
        # best-effort fallback
        try:
            return THEME.text(rendered)
        except (AttributeError, TypeError):
            return rendered


# Delegate log() to the new centralized logging module
from clippy.log import log  # noqa: E402,F401


# sanitize non-ASCII to a safe subset for overlays/filenames
def fix_ascii(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ]+", "", str(s))


# convert variables in the config to actual values
def replace_vars(s, m):
    _cache = _cfg_get("cache", "")
    s = s.replace("{cache}", _cache)
    s = s.replace("{message_id}", str(m[0]))
    # Escape single quotes for ffmpeg drawtext text argument
    author = (m[2] or "").replace("'", "\\'")
    s = s.replace("{author}", author)
    # Normalize font path to forward slashes for ffmpeg on Windows
    _fontfile = _cfg_get("fontfile", None)
    _font = (
        _fontfile.replace("\\", "/").replace("\\", "/") if isinstance(_fontfile, str) else _fontfile
    )
    # When used inside filter_complex with single quotes around parameters, keep fontfile quoted
    # The template expects fontfile='{fontfile}' so we only need to inject the raw path here
    s = s.replace("{fontfile}", _font)
    s = s.replace("{bitrate}", _cfg_get("bitrate", ""))
    s = s.replace("{audio_bitrate}", _cfg_get("audio_bitrate", ""))
    s = s.replace("{fps}", _cfg_get("fps", ""))
    s = s.replace("{resolution}", _cfg_get("resolution", ""))
    # Encoder tuning parameters
    s = s.replace("{cq}", _cfg_get("cq", ""))
    s = s.replace("{gop}", _cfg_get("gop", ""))
    s = s.replace("{rc_lookahead}", _cfg_get("rc_lookahead", ""))
    s = s.replace("{spatial_aq}", _cfg_get("spatial_aq", ""))
    s = s.replace("{aq_strength}", _cfg_get("aq_strength", ""))
    s = s.replace("{temporal_aq}", _cfg_get("temporal_aq", ""))
    s = s.replace("{nvenc_preset}", _cfg_get("nvenc_preset", ""))
    # Container settings
    s = s.replace("{ext}", _cfg_get("container_ext", "mp4"))
    s = s.replace("{container_flags}", _cfg_get("container_flags", "-movflags +faststart"))
    # yt-dlp format string (modelled on the typed config)
    s = s.replace("{yt_format}", _cfg_get("yt_format", ""))
    # ffmpeg path into youtubeDl options (unmodelled binary path)
    try:
        from clippy.config import ffmpeg as _ff

        s = s.replace("{ffmpeg_path}", _ff)
    except ImportError:
        pass
    return s


def resolve_transitions_dir() -> str:
    try:
        env_dir = os.getenv("TRANSITIONS_DIR")
        if env_dir:
            return os.path.abspath(env_dir)
    except OSError:
        pass
    roots: list[str] = []
    try:
        import clippy.config as _cfg  # type: ignore

        cfg_dir = getattr(_cfg, "transitions_dir", None)
        if cfg_dir:
            roots.append(os.path.abspath(str(cfg_dir)))
    except (ImportError, OSError):
        pass
    # Source roots only: repo and CWD
    # Repo and CWD fallbacks
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        roots += [os.path.join(repo_dir, "..", "transitions")]
    except OSError:
        pass
    try:
        cwd = os.getcwd()
        roots += [os.path.join(cwd, "transitions")]
    except OSError:
        pass
    for r in roots:
        try:
            if r and os.path.isdir(r):
                return os.path.abspath(r)
        except OSError:
            continue
    try:
        return os.path.abspath("transitions")
    except OSError:
        return os.path.abspath("transitions")


def active_profile_name() -> str:
    """Name of the profile in effect, or "" when none is selected."""
    try:
        import clippy.config as _cfg  # type: ignore

        return str(getattr(_cfg, "active_profile", "") or "").strip()
    except (ImportError, OSError):
        return ""


def profile_asset_dir(root: str | None = None, profile: str | None = None) -> str | None:
    """``<transitions>/<profile>`` when that folder exists, else None.

    Per-streamer branding lives in its own folder so one install can hold several
    sets of intros and outros; shared assets like static.mp4 stay in the root and
    are still found by the fallback below.
    """
    name = profile if profile is not None else active_profile_name()
    if not name:
        return None
    try:
        base = os.path.abspath(root or resolve_transitions_dir())
        candidate = os.path.join(base, name)
        return candidate if os.path.isdir(candidate) else None
    except OSError:
        return None


def asset_search_dirs(root: str | None = None) -> list[str]:
    """Where to look for an asset, most specific first."""
    base = os.path.abspath(root or resolve_transitions_dir())
    dirs = []
    profile_dir = profile_asset_dir(base)
    if profile_dir:
        dirs.append(profile_dir)
    dirs.append(base)
    return dirs


def find_transition_file(name: str) -> str | None:
    """Find a transition asset by name across all known roots.

    Searches common roots (TRANSITIONS_DIR, config transitions_dir, repo, CWD) and returns the first match.
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
        env_dir = os.getenv("TRANSITIONS_DIR")
        if env_dir:
            candidates.append(os.path.abspath(env_dir))
        # Config-specified dir
        try:
            import clippy.config as _cfg  # type: ignore

            cfg_dir = getattr(_cfg, "transitions_dir", None)
            if cfg_dir:
                candidates.append(os.path.abspath(str(cfg_dir)))
        except (ImportError, OSError):
            pass

        def _add(base: str):
            candidates.append(os.path.join(base, "transitions"))

        try:
            repo_dir = os.path.dirname(os.path.abspath(__file__))
            _add(repo_dir)
        except OSError:
            pass
        try:
            cwd = os.getcwd()
            _add(cwd)
        except OSError:
            pass
        # Search <root>/<profile>/ before <root>/ so a profile's own intro wins
        # over a same-named shared one.
        profile = active_profile_name()
        for root in candidates:
            for base in ([os.path.join(root, profile)] if profile else []) + [root]:
                try:
                    p = os.path.join(base, name)
                    if os.path.exists(p):
                        return os.path.abspath(p)
                except OSError:
                    continue
        return None
    except (OSError, TypeError, ValueError):
        return None


def _dedupe_names_keep_order(items: list[str]) -> list[str]:
    """Return unique basenames, preserving first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = os.path.basename(str(item).strip())
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def discover_transition_files(transitions_dir: str | None = None) -> list[str]:
    """Discover transition clips from the transitions directory.

    Only files matching the traditional `transition_*` naming pattern are included
    when discovery is used.
    """
    found: list[str] = []
    # Profile folder first: _dedupe_names_keep_order keeps the first of a
    # duplicate basename, so a profile's transition_01.mp4 shadows the shared one.
    for root in asset_search_dirs(transitions_dir):
        try:
            for entry in sorted(os.listdir(root)):
                full = os.path.join(root, entry)
                if not os.path.isfile(full):
                    continue
                _stem, ext = os.path.splitext(entry)
                if ext.lower() not in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
                    continue
                if entry.lower().startswith("transition_"):
                    found.append(entry)
        except OSError:
            continue
    return _dedupe_names_keep_order(found)


def resolve_transition_pool(
    transitions_dir: str | None = None,
    configured: list[str] | None = None,
    mode: str | None = None,
    exclude: list[str] | None = None,
) -> list[str]:
    """Resolve the final eligible random-transition pool.

    Modes:
      - explicit: use only the configured `transitions` list
      - discover: scan the transitions directory for `transition_*` clips
      - hybrid: combine both sources
    """
    configured_list = _dedupe_names_keep_order(
        list(configured)
        if isinstance(configured, (list, tuple))
        else list(_cfg_get("transitions", []) or [])
    )
    discovered_list = discover_transition_files(transitions_dir)
    raw_mode = str(mode or _cfg_get("transition_mode", "explicit") or "explicit")
    resolved_mode = raw_mode.strip().lower()
    if resolved_mode not in {"explicit", "discover", "hybrid"}:
        resolved_mode = "explicit"
    exclude_list = (
        list(exclude)
        if isinstance(exclude, (list, tuple))
        else list(_cfg_get("transition_exclude", []) or [])
    )
    excluded = {
        os.path.basename(str(name).strip()).lower() for name in exclude_list if str(name).strip()
    }

    if resolved_mode == "discover":
        pool = list(discovered_list)
    elif resolved_mode == "hybrid":
        pool = _dedupe_names_keep_order(configured_list + discovered_list)
    else:
        pool = list(configured_list)

    resolved: list[str] = []
    missing: list[str] = []
    for name in pool:
        basename = os.path.basename(str(name).strip())
        if not basename or basename.lower() in excluded:
            continue
        if find_transition_file(name):
            resolved.append(basename)
        else:
            missing.append(basename)

    if missing:
        try:
            log(
                "WARN These configured transitions were not found and will be skipped: "
                + ", ".join(missing),
                2,
            )
        except Exception:
            pass
    return _dedupe_names_keep_order(resolved)


# clean up the cache folders and get ready to do some work
def prep_work():
    # make our workspace
    def _display_path(p: str) -> str:
        try:
            return os.path.abspath(p)
        except OSError:
            return p

    def _ensure_dir(path: str, label: str):
        try:
            if not os.path.exists(path):
                log(f"creating new {label} directory at " + _display_path(path), 1)
                os.makedirs(path, exist_ok=True)
        except OSError as e:
            log("Failed to create " + str(label) + " dir: " + str(e), 5)

    def _ensure_readme(path: str, content: str):
        try:
            readme_path = os.path.join(path, "README.md")
            if not os.path.exists(readme_path):
                os.makedirs(path, exist_ok=True)
                with open(readme_path, "w", encoding="utf-8") as f:
                    f.write(content)
        except OSError as e:
            log("Failed to write README in " + str(path) + ": " + str(e), 5)

    # cache dir
    _cache = _cfg_get("cache", "./cache")
    _ensure_dir(_cache, "cache")
    _ensure_readme(
        _cache,
        (
            "# cache\n\n"
            "Temporary working directory.\n\n"
            "- Each clip gets its own subfolder with intermediate files (clip.mp4, normalized.mp4, preview.png).\n"
            "- Stage 2 outputs are written as complete_<date>_<idx>.<ext> before being moved to output/.\n"
        ),
    )

    # output dir
    _output = _cfg_get("output", "./output")
    _ensure_dir(_output, "output")
    _ensure_readme(
        _output,
        (
            "# output\n\n"
            "Final compilations are moved here after encoding.\n\n"
            "- Filenames include the broadcaster and date range.\n"
            "- Use --overwrite-output to replace existing files, else _1, _2 suffixes are added.\n"
        ),
    )

    # transitions dir
    transitions_dir = resolve_transitions_dir()
    _ensure_readme(
        transitions_dir,
        (
            "# transitions\n\n"
            "Put your intro/outro/transition clips here.\n\n"
            "- static.mp4 is REQUIRED.\n"
            "- You can provide intro_2.mp4, outro_2.mp4, transition_01.mp4, etc.\n"
        ),
    )
    try:
        static_path = os.path.join(transitions_dir, "static.mp4")
        if not os.path.exists(static_path):
            log(
                "WARN transitions/static.mp4 not found. Run 'clippy deps' to fetch the "
                "default one, or place your own in the transitions folder.",
                1,
            )
    except OSError as e:
        log("Static file check error: " + str(e), 5)
