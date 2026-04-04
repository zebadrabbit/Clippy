"""Progress dashboard — live view of pipeline execution."""

from __future__ import annotations

import io
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, ProgressBar, RichLog, Static

# ---------------------------------------------------------------------------
# Pipeline callback protocol (consumed by both TUI and CLI)
# ---------------------------------------------------------------------------


class PipelineCallbacks(Protocol):
    """Interface for pipeline progress reporting."""

    def on_clip_status(self, clip_id: str, status: str, progress: float | None = None) -> None: ...

    def on_stage_change(self, stage: str) -> None: ...

    def on_concat_progress(self, index: int, progress: float) -> None: ...

    def on_log(self, message: str, level: int = 0) -> None: ...


# ---------------------------------------------------------------------------
# Logging handler that routes into a RichLog widget
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class _TuiLogHandler(logging.Handler):
    """Logging handler that writes records into a Textual RichLog widget."""

    def __init__(self, log_widget: RichLog):
        super().__init__()
        self._log_widget = log_widget

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            # Strip ANSI escape codes — RichLog uses Rich markup, not ANSI
            clean = _ANSI_RE.sub("", msg)
            if clean.strip():
                self._log_widget.write(clean)
        except Exception:
            pass


class _StdoutCapture(io.TextIOBase):
    """File-like object that captures writes and sends them to a RichLog."""

    def __init__(self, log_widget: RichLog):
        self._log_widget = log_widget
        self._buf = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            clean = _ANSI_RE.sub("", line).strip()
            if clean:
                try:
                    self._log_widget.write(clean)
                except Exception:
                    pass
        return len(s)

    def flush(self) -> None:
        if self._buf.strip():
            clean = _ANSI_RE.sub("", self._buf).strip()
            if clean:
                try:
                    self._log_widget.write(clean)
                except Exception:
                    pass
            self._buf = ""

    def isatty(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Progress Screen
# ---------------------------------------------------------------------------


class ProgressScreen(Screen):
    """Live progress dashboard during pipeline execution."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="screen-container"):
            yield Static("Processing", classes="screen-title")

            with Vertical(classes="progress-section"):
                yield Label("Overall Progress")
                yield ProgressBar(total=100, id="overall-progress")

            yield Label("Stage: Initializing...", id="stage-label")

            with Vertical(classes="progress-section"):
                yield Label("Compilation Progress")
                yield ProgressBar(total=100, id="concat-progress")

            yield Label("Log")
            yield RichLog(id="log-panel", classes="log-panel", markup=True)

            with Horizontal(classes="button-bar"):
                yield Button("Cancel", variant="error", id="cancel-btn")

    def on_mount(self) -> None:
        self._log("[bold cyan]Pipeline starting...[/]")

        # Start the pipeline in a worker thread
        self.run_worker(self._run_pipeline, thread=True)

    def _log(self, msg: str) -> None:
        try:
            self.query_one("#log-panel", RichLog).write(msg)
        except Exception:
            pass

    def _set_stage(self, stage: str) -> None:
        try:
            self.query_one("#stage-label", Label).update(f"Stage: {stage}")
        except Exception:
            pass

    def _set_overall(self, pct: float) -> None:
        try:
            self.query_one("#overall-progress", ProgressBar).update(progress=pct)
        except Exception:
            pass

    def _set_concat(self, pct: float) -> None:
        try:
            self.query_one("#concat-progress", ProgressBar).update(progress=pct)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Output capture context manager
    # ------------------------------------------------------------------

    def _capture_output(self):
        """Return a context manager that redirects logger + stdout to the TUI log."""
        screen = self

        class _Capture:
            def __enter__(self_ctx):
                log_widget = screen.query_one("#log-panel", RichLog)

                # Add TUI handler to the clippy logger
                self_ctx._handler = _TuiLogHandler(log_widget)
                self_ctx._handler.setFormatter(logging.Formatter("%(message)s"))
                clippy_logger = logging.getLogger("clippy")
                clippy_logger.addHandler(self_ctx._handler)

                # Temporarily disable existing stdout handlers to avoid
                # duplicate messages (original handler → stdout → capture
                # AND TUI handler → RichLog)
                self_ctx._disabled_handlers = []
                for h in clippy_logger.handlers:
                    if h is not self_ctx._handler and isinstance(
                        h, logging.StreamHandler
                    ):
                        h.setLevel(logging.CRITICAL + 1)
                        self_ctx._disabled_handlers.append(h)

                # Redirect stdout so print() calls land in the log
                self_ctx._old_stdout = sys.stdout
                sys.stdout = _StdoutCapture(log_widget)

                return self_ctx

            def __exit__(self_ctx, *exc):
                sys.stdout = self_ctx._old_stdout
                clippy_logger = logging.getLogger("clippy")
                clippy_logger.removeHandler(self_ctx._handler)
                # Restore original handlers
                for h in self_ctx._disabled_handlers:
                    h.setLevel(logging.NOTSET)

        return _Capture()

    # ------------------------------------------------------------------
    # Pipeline execution
    # ------------------------------------------------------------------

    async def _run_pipeline(self) -> None:  # noqa: C901
        """Execute the full pipeline in a background thread."""
        import clippy.config as _cfg_mod
        from clippy.naming import (
            ensure_unique_names,
            finalize_outputs,
            sanitize_filename,
        )
        from clippy.pipeline import create_compilations_from, stage_one, stage_two
        from clippy.twitch_ingest import (
            build_clip_rows,
            fetch_clips,
            fetch_creator_avatars,
            get_app_access_token,
            load_credentials,
            resolve_user,
        )
        from clippy.utils import prep_work
        from clippy.window import resolve_date_window

        wf = self.app.workflow
        cs = wf.get("clip_settings", {})
        creds = wf.get("credentials", {})
        wf.get("encoder_params")  # consumed later via workflow dict

        broadcaster = cs.get("broadcaster", "")
        if not broadcaster:
            self._log("[bold red]Error: No broadcaster specified[/]")
            return

        sizing_mode = cs.get("sizing_mode", "count")
        clips_per_comp = int(cs.get("clips_per_comp", 12))
        compilations = int(cs.get("compilations", 2))
        min_views = int(cs.get("min_views", 0))
        auto_expand = cs.get("auto_expand", True)
        nostalgia_mode = cs.get("nostalgia_mode", False)
        target_duration_secs = float(cs.get("target_duration_min", 0)) * 60
        target_total = clips_per_comp * compilations

        # Sync TUI values into config module so pipeline reads them
        _cfg_mod.amountOfClips = clips_per_comp
        _cfg_mod.amountOfCompilations = compilations
        _cfg_mod.reactionThreshold = min_views

        # Sync transition settings
        tr = wf.get("transitions", {})
        if tr.get("selected_transitions") is not None:
            _cfg_mod.transitions = tr["selected_transitions"]
        if tr.get("transitions_weights"):
            _cfg_mod.transitions_weights = tr["transitions_weights"]
        if "transition_probability" in tr:
            _cfg_mod.transition_probability = tr["transition_probability"]
        if "transition_cooldown" in tr:
            _cfg_mod.transition_cooldown = tr["transition_cooldown"]
        if "no_random_transitions" in tr:
            _cfg_mod.no_random_transitions = tr["no_random_transitions"]
        if "audio_normalize_clips" in tr:
            _cfg_mod.audio_normalize_clips = tr["audio_normalize_clips"]
        if "audio_normalize_transitions" in tr:
            _cfg_mod.audio_normalize_transitions = tr["audio_normalize_transitions"]
        if "silence_static" in tr:
            _cfg_mod.silence_static = tr["silence_static"]
        if "no_overlay" in tr:
            _cfg_mod.enable_overlay = not tr["no_overlay"]
        if tr.get("transitions_dir"):
            _cfg_mod.transitions_dir = tr["transitions_dir"]
            os.environ["TRANSITIONS_DIR"] = tr["transitions_dir"]

        start_date = cs.get("start", "")
        end_date = cs.get("end", "")

        try:
            # ---- Auth ----
            self._set_stage("Authenticating")
            self._log("Authenticating with Twitch...")
            self._set_overall(5)

            cid, secret = load_credentials(
                creds.get("client_id") or None,
                creds.get("client_secret") or None,
            )
            token = get_app_access_token(cid, secret)
            self._log("[green]Authenticated successfully[/]")

            # ---- Resolve broadcaster ----
            self._set_stage("Resolving broadcaster")
            self._set_overall(10)
            self._log(f"Resolving broadcaster: {broadcaster}")

            user = resolve_user(broadcaster, cid, token)
            if not user:
                self._log(f"[bold red]Could not resolve broadcaster: {broadcaster}[/]")
                return
            broadcaster_id = user["id"]
            self._log(f"Broadcaster ID: {broadcaster_id}")

            # ---- Prep workspace ----
            with self._capture_output():
                prep_work()

            # ---- Resolve date window ----
            window = resolve_date_window(start_date or None, end_date or None)

            # ---- Fetch clips ----
            self._set_stage("Fetching clips")
            self._set_overall(15)
            self._log(f"Fetching clips (window: {window[0] or 'auto'} → {window[1] or 'now'})...")

            with self._capture_output():
                clips = fetch_clips(
                    broadcaster_id=broadcaster_id,
                    client_id=cid,
                    token=token,
                    started_at=window[0],
                    ended_at=window[1],
                    max_clips=max(target_total * 3, 100),
                )
            self._log(f"Fetched {len(clips)} clips from Twitch")

            # ---- Filter by min views ----
            filtered = [c for c in clips if int(c.get("view_count", 0)) >= min_views]
            self._log(f"After view filter (>= {min_views}): {len(filtered)} clips")

            # ---- Auto-expand ----
            if auto_expand and len(filtered) < target_total:
                self._set_stage("Auto-expanding date range")
                self._log(
                    f"Need {target_total} clips, have {len(filtered)} — expanding date range..."
                )
                filtered, window = self._auto_expand(
                    filtered,
                    target_total,
                    min_views,
                    broadcaster_id,
                    cid,
                    token,
                    window,
                )
                self._log(f"After auto-expand: {len(filtered)} clips")

            # ---- Nostalgia mode ----
            if nostalgia_mode and len(filtered) >= target_total:
                self._set_stage("Adding nostalgia clips")
                self._log("Nostalgia mode: fetching older clips (>6 months)...")
                filtered = self._add_nostalgia_clips(
                    filtered,
                    target_total,
                    min_views,
                    broadcaster_id,
                    cid,
                    token,
                )
                self._log(f"After nostalgia mix: {len(filtered)} clips")

            if len(filtered) < target_total:
                self._log(
                    f"[bold yellow]Warning: Only {len(filtered)} clips available "
                    f"(requested {target_total})[/]"
                )
                if not filtered:
                    self._log("[bold red]No clips to process — aborting[/]")
                    return

            self._set_overall(25)

            # ---- Build clip rows ----
            self._set_stage("Building clip metadata")
            self._log("Fetching creator avatars...")
            with self._capture_output():
                avatar_map = fetch_creator_avatars(filtered, cid, token)
                rows = build_clip_rows(filtered, avatar_map)

            comps = create_compilations_from(
                rows,
                target_duration_secs=target_duration_secs if sizing_mode == "duration" else 0,
            )
            actual_comps = len(comps)
            total_clips = sum(len(c) for c in comps)
            self._log(f"Created {actual_comps} compilation(s) " f"with {total_clips} total clips")
            if sizing_mode == "duration":
                for i, comp in enumerate(comps):
                    dur = sum(c.duration for c in comp if c.duration > 0)
                    self._log(f"  Compilation {i+1}: {len(comp)} clips, ~{dur/60:.1f} min")

            self._set_overall(30)

            # ---- Stage 1: process clips ----
            self._set_stage("Stage 1 — Processing clips")
            self._log("[bold cyan]Stage 1: Processing clips (download, normalize, overlay)...[/]")
            with self._capture_output():
                stage_one(comps)
            self._set_overall(60)
            self._log("[green]Stage 1 complete[/]")

            # ---- Build final names ----
            getattr(_cfg_mod, "cache", "cache")  # reserved for future use
            output_dir = getattr(_cfg_mod, "output", "output")
            ext = getattr(_cfg_mod, "container_ext", "mp4")
            b_safe = sanitize_filename(broadcaster.lower()) or "broadcaster"
            start_iso, end_iso = window

            def _date_part(iso_str: Optional[str]) -> Optional[str]:
                if not iso_str:
                    return None
                return iso_str.split("T", 1)[0]

            if start_iso or end_iso:
                s_part = _date_part(start_iso) or "unknown"
                e_part = _date_part(end_iso) or s_part
                date_range = f"{s_part}_to_{e_part}"
            else:
                date_range = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            base_names = []
            for i in range(actual_comps):
                if actual_comps == 1:
                    base_names.append(f"{b_safe}_{date_range}_compilation.{ext}")
                else:
                    base_names.append(f"{b_safe}_{date_range}_part{i+1}.{ext}")
            final_names = ensure_unique_names(base_names, output_dir, False)

            # ---- Stage 2: concatenate ----
            self._set_stage("Stage 2 — Concatenating")
            self._log("[bold cyan]Stage 2: Building compilations...[/]")
            self._set_overall(65)
            with self._capture_output():
                stage_two(comps, final_names)
            self._set_overall(90)
            self._log("[green]Stage 2 complete[/]")

            # ---- Finalize ----
            self._set_stage("Finalizing")
            self._log("Finalizing outputs...")
            with self._capture_output():
                finals = finalize_outputs(
                    broadcaster,
                    window,
                    actual_comps,
                    False,  # keep_cache
                    final_names=final_names,
                    overwrite_output=False,
                    purge_cache=False,
                )
            self._set_overall(100)
            self._set_stage("Complete")

            # Navigate to summary screen
            self.app.call_from_thread(
                self.app.advance_to,
                "summary",
                output_files=finals,
                compilations=comps,
            )

        except Exception as e:
            self._log(f"[bold red]Error: {e}[/]")
            import traceback

            self._log(traceback.format_exc())

    # ------------------------------------------------------------------
    # Auto-expand helper
    # ------------------------------------------------------------------

    def _auto_expand(
        self,
        filtered: list[dict],
        target_total: int,
        min_views: int,
        broadcaster_id: str,
        cid: str,
        token: str,
        window: tuple,
    ) -> tuple[list[dict], tuple]:
        """Extend clips by fetching outside the date range (newest first)."""
        from clippy.twitch_ingest import fetch_clips

        collected = list(filtered)
        seen_ids = {c.get("id") for c in collected if c.get("id")}

        end_dt = self._parse_iso(window[1]) or datetime.now(timezone.utc)
        start_dt = self._parse_iso(window[0])
        if not start_dt:
            start_dt = end_dt - timedelta(days=3)

        step_days = 7
        max_lookback_days = 90
        current_start = start_dt
        lookback_limit = end_dt - timedelta(days=max_lookback_days)

        while len(collected) < target_total and current_start > lookback_limit:
            new_start = current_start - timedelta(days=step_days)
            new_start_iso = new_start.isoformat().replace("+00:00", "Z")
            current_end_iso = current_start.isoformat().replace("+00:00", "Z")

            seg_clips = fetch_clips(
                broadcaster_id=broadcaster_id,
                client_id=cid,
                token=token,
                started_at=new_start_iso,
                ended_at=current_end_iso,
                max_clips=target_total - len(collected) + 10,
            )

            for c in seg_clips:
                if int(c.get("view_count", 0)) >= min_views:
                    c_id = c.get("id")
                    if c_id and c_id not in seen_ids:
                        seen_ids.add(c_id)
                        collected.append(c)

            self._log(f"  expanded to {len(collected)}/{target_total} clips")
            current_start = new_start

        new_window = (
            current_start.isoformat().replace("+00:00", "Z"),
            window[1],
        )
        return collected, new_window

    # ------------------------------------------------------------------
    # Nostalgia mode helper
    # ------------------------------------------------------------------

    def _add_nostalgia_clips(
        self,
        filtered: list[dict],
        target_total: int,
        min_views: int,
        broadcaster_id: str,
        cid: str,
        token: str,
    ) -> list[dict]:
        """Mix in random older clips (>6 months) replacing some of the existing selection."""
        import random

        from clippy.twitch_ingest import fetch_clips

        six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)
        one_year_ago = six_months_ago - timedelta(days=180)

        old_clips = fetch_clips(
            broadcaster_id=broadcaster_id,
            client_id=cid,
            token=token,
            started_at=one_year_ago.isoformat().replace("+00:00", "Z"),
            ended_at=six_months_ago.isoformat().replace("+00:00", "Z"),
            max_clips=50,
        )

        old_filtered = [c for c in old_clips if int(c.get("view_count", 0)) >= min_views]
        if not old_filtered:
            self._log("[yellow]No nostalgia clips found (>6 months old)[/]")
            return filtered

        seen_ids = {c.get("id") for c in filtered}
        old_unique = [c for c in old_filtered if c.get("id") not in seen_ids]
        if not old_unique:
            return filtered

        # Replace ~20% of clips with nostalgia clips
        n_nostalgia = max(1, target_total // 5)
        n_nostalgia = min(n_nostalgia, len(old_unique))
        picks = random.sample(old_unique, n_nostalgia)

        self._log(f"Mixing in {len(picks)} nostalgia clip(s)")

        # Insert nostalgia clips at random positions, keeping total at target
        result = list(filtered[: target_total - n_nostalgia])
        for p in picks:
            pos = random.randint(0, len(result))
            result.insert(pos, p)

        return result

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_iso(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self._log("[bold red]Cancelling...[/]")
            try:
                from clippy.pipeline import request_shutdown

                request_shutdown()
            except Exception:
                pass
            self.app.pop_screen()
