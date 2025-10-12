from __future__ import annotations

import os
import re
import shutil
import time
from datetime import datetime
from typing import List, Optional, Tuple


def sanitize_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:80]


def ensure_unique_names(base_names: List[str], out_dir: str, overwrite: bool) -> List[str]:
    """Return names unique within out_dir by appending _1, _2, ... before extension.
    If overwrite=True, returns base_names unchanged.
    Ensures uniqueness within this batch and against existing files on disk.
    """
    if overwrite:
        return list(base_names)
    used: set[str] = set()
    try:
        for fname in os.listdir(out_dir):
            used.add(fname.lower())
    except Exception:
        pass
    result: list[str] = []
    for name in base_names:
        if name.lower() not in used and name.lower() not in (n.lower() for n in result):
            result.append(name)
            used.add(name.lower())
            continue
        # split name/ext
        root, ext = os.path.splitext(name)
        k = 1
        while True:
            cand = f"{root}_{k}{ext}"
            low = cand.lower()
            if low not in used and low not in (n.lower() for n in result):
                result.append(cand)
                used.add(low)
                break
            k += 1
    return result


def finalize_outputs(
    broadcaster: str,
    window: Tuple[Optional[str], Optional[str]],
    compilation_count: int,
    keep_cache: bool,
    final_names: Optional[List[str]] = None,
    overwrite_output: bool = False,
    purge_cache: bool = False,
) -> List[str]:
    """Move compiled files from cache to output with improved naming then optionally clean cache."""
    # Import late to avoid circulars
    from clippy.config import cache, output
    from clippy.utils import log  # local import to avoid circular

    log("Finalizing outputs", 1)
    try:
        b_name = sanitize_filename(broadcaster.lower()) or "broadcaster"
        start_iso, end_iso = window

        # derive date segment
        def _date_part(iso_str: Optional[str]) -> Optional[str]:
            if not iso_str:
                return None
            return iso_str.split("T", 1)[0]

        if start_iso or end_iso:
            s_part = _date_part(start_iso) or "unknown"
            e_part = _date_part(end_iso) or s_part
            date_range = f"{s_part}_to_{e_part}"
        else:
            date_range = datetime.utcnow().strftime("%Y-%m-%d")
        # Determine container extension used by ffmpeg for cache outputs
        try:
            from clippy.config import container_ext as _ext_cfg
        except Exception:
            _ext_cfg = "mp4"
        # Use provided final names (preferred), else derive from broadcaster/date
        if final_names is None:
            final_names = []
            for i in range(compilation_count):
                if compilation_count == 1:
                    final_names.append(f"{b_name}_{date_range}_compilation.{_ext_cfg}")
                else:
                    final_names.append(f"{b_name}_{date_range}_part{i+1}.{_ext_cfg}")

        moved = 0
        moved_files: list[str] = []
        missing_indices: list[int] = []
        # Move cache outputs to output dir with final names using their index
        for i in range(compilation_count):
            # cache file pattern produced by ffmpegBuildSegments
            date_str = time.strftime("%d_%m_%y")
            cache_name = f"complete_{date_str}_{i}.{_ext_cfg}"
            src = os.path.join(cache, cache_name)
            if not os.path.exists(src):
                # Fallback: scan for matching idx
                for fname in os.listdir(cache):
                    if fname.startswith("complete_") and fname.endswith(f"_{i}.{_ext_cfg}"):
                        src = os.path.join(cache, fname)
                        break
            if os.path.exists(src):
                dest = os.path.join(output, final_names[i])
                # If overwrite requested, remove existing file to avoid errors
                if overwrite_output and os.path.exists(dest):
                    try:
                        os.remove(dest)
                    except Exception:
                        pass
                # If still exists and overwrite is False, auto-suffix here as a last resort
                if (not overwrite_output) and os.path.exists(dest):
                    root, ext = os.path.splitext(final_names[i])
                    k = 1
                    while True:
                        cand = f"{root}_{k}{ext}"
                        _new = os.path.join(output, cand)
                        if not os.path.exists(_new):
                            dest = _new
                            # Update name so manifest reports actual file
                            final_names[i] = cand
                            break
                        k += 1
                shutil.move(src, dest)
                moved += 1
                moved_files.append(os.path.basename(dest))
            else:
                missing_indices.append(i)
        if moved_files:
            try:
                log("Moved " + str(moved) + " file(s) to output: " + ", ".join(moved_files), 2)
            except Exception:
                log("Moved " + str(moved) + " file(s) to output", 2)
        else:
            log("Moved " + str(moved) + " file(s) to output", 2)
        if missing_indices:
            try:
                log(
                    "WARN Missing compiled output(s) in cache for index(es): "
                    + ", ".join(str(i) for i in missing_indices),
                    2,
                )
            except Exception:
                pass
    except Exception as e:  # pragma: no cover
        log("Finalize failed: " + str(e), 5)
        return []

    if keep_cache and not purge_cache:
        log("Cache retained (--keep-cache set)", 0)
        return final_names
    # clean cache except leave directory itself
    log("Cleaning cache", 1)
    try:
        preserve_set = set()
        if not purge_cache:
            try:
                from clippy.config import cache_preserve_dirs as _preserve
            except Exception:
                _preserve = []
            preserve_set = {d.strip().lower() for d in _preserve if isinstance(d, str)}
        for entry in os.listdir(cache):
            if entry.strip().lower() in preserve_set:
                continue
            path = os.path.join(cache, entry)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
            except OSError:
                pass
        log("Cache cleaned", 2)
    except Exception as e:  # pragma: no cover
        log("Cache cleanup failed: " + str(e), 5)
    return final_names
