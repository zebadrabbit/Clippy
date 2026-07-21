"""Transitions screen — a two-pane transfer list for choosing the clip pool."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from clippy.tui.bbs import BBSScreen


def _resolve_transitions_path() -> str:
    """Return the absolute transitions directory path."""
    try:
        from clippy.utils import resolve_transitions_dir

        return resolve_transitions_dir()
    except Exception:
        import os

        return os.path.abspath("transitions")


def _discover(path: str) -> list[str]:
    """Transition clips present on disk, or an empty list if the path is bad."""
    try:
        from clippy.utils import discover_transition_files

        return list(discover_transition_files(path))
    except Exception:
        return []


def _current_pool(path: str) -> list[str]:
    """What this config would use today, so the panes open on the status quo."""
    try:
        from clippy.utils import resolve_transition_pool

        return list(resolve_transition_pool(transitions_dir=path) or [])
    except Exception:
        return []


def _safe_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_float(value: str, default: float, minimum: float, maximum: float) -> float:
    parsed = _safe_float(value, default)
    return max(minimum, min(maximum, parsed))


def _bounded_int(value: str, default: int, minimum: int) -> int:
    parsed = _safe_int(value, default)
    return max(minimum, parsed)


class TransitionsScreen(BBSScreen):
    """Step 5: pick which transition clips are eligible.

    A two-pane transfer list: AVAILABLE on the left, SELECTED on the right. The
    right pane is the whole answer -- it is exactly the pool the pipeline draws
    from, which is what ``explicit`` mode has always meant. That makes the old
    mode / exclude-list text boxes redundant: "select all" is discover mode
    spelled out, and leaving a clip on the left is the denylist.
    """

    STEP = 5
    STEP_TITLE = "Transitions"
    KEYS = "[<-/->] move  [SPACE] move  [A] all  [N] none  [TAB] pane  [ENTER] ok"

    HINTS = {
        "transitions-dir": "folder holding your transition clips and static.mp4",
        "available-list": "clips found on disk that will NOT be used",
        "selected-list": "the pool random transitions are drawn from",
        "transition-prob": "chance of a transition between clips: 0.0 never, 1.0 always",
        "transition-cooldown": "do not repeat a transition within the last N picks (0 = off)",
    }
    DEFAULT_HINT = "Move clips between the panes with the arrow keys or SPACE."

    BINDINGS = [
        Binding("right", "move_right", "select", show=False),
        Binding("left", "move_left", "deselect", show=False),
        Binding("space", "move_either", "move", show=False),
        Binding("a", "select_all", "all", show=False),
        Binding("n", "select_none", "none", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._available: list[str] = []
        self._selected: list[str] = []

    # -- composition --------------------------------------------------------

    def compose(self) -> ComposeResult:
        cfg = self.app.config

        yield self.title_bar()
        with Vertical(classes="screen-container"):
            with Horizontal(classes="bbs-row"):
                yield Label("Directory ")
                yield Input(
                    value=_resolve_transitions_path(),
                    placeholder="./transitions",
                    id="transitions-dir",
                    classes="w-wide",
                )

            with Horizontal(id="picker"):
                with Vertical(classes="pane"):
                    yield Static("AVAILABLE", classes="bbs-section")
                    yield OptionList(id="available-list", classes="pane-list")
                with Vertical(classes="pane"):
                    yield Static("SELECTED", classes="bbs-section")
                    yield OptionList(id="selected-list", classes="pane-list")

            with Horizontal(classes="bbs-row"):
                yield Label("Prob ")
                yield Input(
                    value=str(cfg.sequencing.transition_probability),
                    id="transition-prob",
                    classes="w-tiny",
                )
                yield Label("  Cooldown ")
                yield Input(
                    value=str(cfg.sequencing.transition_cooldown),
                    id="transition-cooldown",
                    classes="w-tiny",
                )
                yield Static("", id="pool-count", classes="bbs-dim")

            yield self.progress_bar()
            with Horizontal(classes="button-bar"):
                yield Button("< Back", id="back-btn")
                yield Button("Next >", variant="primary", id="next-btn")

        yield from self.status_bar()

    def on_mount(self) -> None:
        self._load(_resolve_transitions_path())

    # -- pane state ---------------------------------------------------------

    def _load(self, path: str) -> None:
        """Seed the panes; selected starts as whatever this config resolves to."""
        found = _discover(path)
        current = [name for name in _current_pool(path) if name in found]
        self._selected = current
        self._available = [name for name in found if name not in self._selected]
        if not self._selected:
            # Nothing resolvable yet -- offer everything rather than an empty pool.
            self._available = list(found)
        self._refresh()

    def _refresh(self) -> None:
        for list_id, items in (
            ("#available-list", self._available),
            ("#selected-list", self._selected),
        ):
            widget = self.query_one(list_id, OptionList)
            previous = widget.highlighted
            widget.clear_options()
            for name in items:
                widget.add_option(Option(name, id=name))
            if items:
                widget.highlighted = min(previous or 0, len(items) - 1)
        total = len(self._available) + len(self._selected)
        self.query_one("#pool-count", Static).update(f"  pool: {len(self._selected)} of {total}")

    def _move(self, name: str, *, to_selected: bool) -> None:
        src, dst = (
            (self._available, self._selected) if to_selected else (self._selected, self._available)
        )
        if name in src:
            src.remove(name)
            dst.append(name)
            self._refresh()

    def _highlighted(self, list_id: str) -> str | None:
        widget = self.query_one(list_id, OptionList)
        if widget.highlighted is None or not widget.option_count:
            return None
        return widget.get_option_at_index(widget.highlighted).id

    # -- actions ------------------------------------------------------------

    def action_move_right(self) -> None:
        name = self._highlighted("#available-list")
        if name:
            self._move(name, to_selected=True)

    def action_move_left(self) -> None:
        name = self._highlighted("#selected-list")
        if name:
            self._move(name, to_selected=False)

    def action_move_either(self) -> None:
        """SPACE moves from whichever pane has focus."""
        if getattr(self.focused, "id", None) == "selected-list":
            self.action_move_left()
        else:
            self.action_move_right()

    def action_select_all(self) -> None:
        self._selected.extend(self._available)
        self._available = []
        self._refresh()

    def action_select_none(self) -> None:
        self._available.extend(self._selected)
        self._selected = []
        self._refresh()

    def on_option_list_option_selected(self, event) -> None:
        """ENTER on a row moves it, the way a DOS transfer list behaves."""
        if event.option_list.id == "available-list":
            self._move(event.option.id, to_selected=True)
        elif event.option_list.id == "selected-list":
            self._move(event.option.id, to_selected=False)

    # -- plumbing -----------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "transitions-dir":
            self._load(event.value.strip() or _resolve_transitions_path())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "next-btn":
            self.app.workflow["transitions"] = {
                "transitions_dir": self.query_one("#transitions-dir", Input).value.strip(),
                # The right pane is the pool, so record it explicitly rather than
                # leaning on discover/hybrid plus a denylist.
                "transition_mode": "explicit",
                "selected_transitions": list(self._selected),
                "transition_exclude": [],
                "transition_probability": _bounded_float(
                    self.query_one("#transition-prob", Input).value or "0.35", 0.35, 0.0, 1.0
                ),
                "transition_cooldown": _bounded_int(
                    self.query_one("#transition-cooldown", Input).value or "1", 1, 0
                ),
            }
            self.app.advance_to("audio")
