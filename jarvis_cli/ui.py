"""Terminal output for the Jarvis CLI — colors, tables, prompts, menus.

Standard library only, on purpose: the CLI has to run in a freshly unpacked
ZIP where no virtualenv and not a single dependency exists yet, so nothing
here may import fastapi/requests/rich. Everything the user sees goes through
this module, which is what keeps the output readable instead of a wall of
unformatted prints.

Enable/disable color with NO_COLOR (any value) or JARVIS_CLI_COLOR=0/1.
"""

from __future__ import annotations

import os
import select
import shutil
import sys
import threading
import time

RESET = "\033[0m"

# Plain named colors instead of 256/truecolor: Windows Terminal, PowerShell's
# own console host and macOS Terminal.app all render these, and legibility on
# a light background is better than a pastel 24-bit value.
_ANSI = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "grey": "\033[90m",
    "bred": "\033[91m",
    "bgreen": "\033[92m",
    "byellow": "\033[93m",
    "bcyan": "\033[96m",
    "bwhite": "\033[97m",
}

MARK = {
    "ok": ("OK", "bgreen"),
    "warn": ("!", "byellow"),
    "fail": ("X", "bred"),
    "info": ("i", "bcyan"),
    "step": ("-", "grey"),
    "done": ("+", "bgreen"),
}

_LABELS = {
    "ok": "OK",
    "warn": "Achtung",
    "fail": "Fehler",
    "info": "Info",
    "step": "",
    "done": "",
}


def _enable_windows_vt() -> bool:
    if not sys.platform.startswith("win"):
        return True
    import ctypes

    ok = False
    for std_handle in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
        try:
            handle = ctypes.windll.kernel32.GetStdHandle(std_handle)
            mode = ctypes.c_uint32()
            if not ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                continue
            if ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004):
                ok = True
        except Exception:
            pass
    return ok


def _utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding in ("utf8", "utf8mb4"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def read_key() -> str:
    """One keystroke as a name: up/down/left/right/enter/esc/space/ctrl-c or
    the literal character. Arrow keys and Escape behave the same on Windows
    (msvcrt) and POSIX (raw cbreak terminal), so the menu code above never
    has to care which one it's on."""
    if sys.platform.startswith("win"):
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return {
                "H": "up", "P": "down", "M": "right", "K": "left",
                "G": "home", "O": "end", "I": "pgup", "Q": "pgdown",
                "S": "shifttab", "R": "insert", "D": "delete",
            }.get(msvcrt.getwch(), "unknown")
        return {
            "\r": "enter", "\n": "enter", "\x1b": "esc", "\x03": "ctrl-c",
            " ": "space", "\x08": "backspace",
        }.get(ch, ch)

    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
        if ch != "\x1b":
            return {"\r": "enter", "\n": "enter", "\x03": "ctrl-c",
                    " ": "space", "\x7f": "backspace"}.get(ch, ch)
        # A bare Escape arrives as one byte, an arrow key as three: wait only
        # briefly for the rest, otherwise a plain Escape would freeze the menu.
        if not select.select([sys.stdin], [], [], 0.05)[0]:
            return "esc"
        seq = sys.stdin.read(2)
        return {"[A": "up", "[B": "down", "[C": "right", "[D": "left",
                "[H": "home", "[F": "end", "[5~": "pgup", "[6~": "pgdown",
                "[Z": "shifttab"}.get(seq, "unknown")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


class Ui:
    def __init__(self) -> None:
        self.interactive = sys.stdin.isatty() and sys.stdout.isatty()
        forced = os.environ.get("JARVIS_CLI_COLOR", "").strip().lower()
        if forced in ("0", "no", "false", "off"):
            self.color = False
        elif forced in ("1", "yes", "true", "on"):
            self.color = True
        else:
            self.color = self.interactive and "NO_COLOR" not in os.environ
        if sys.platform.startswith("win"):
            if self.color and not _enable_windows_vt():
                self.color = False
        _utf8_streams()
        self.width = min(shutil.get_terminal_size((100, 30)).columns, 110)
        try:
            "⠋".encode(sys.stdout.encoding or "utf-8")
            self.frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        except (LookupError, UnicodeEncodeError, TypeError):
            self.frames = "|/-\\"
        self._line_open = False
        self._busy = False

    # ---------------------------------------------------------------- output
    def paint(self, text: str, *styles: str) -> str:
        if not self.color or not styles:
            return text
        return "".join(_ANSI[s] for s in styles if s in _ANSI) + text + RESET

    def out(self, text: str = "") -> None:
        self.clear_line()
        print(text)

    def write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()
        self._line_open = not text.endswith("\n")

    def clear_line(self) -> None:
        # Only worth doing while a redrawn line is actually on screen: without
        # ANSI (piped output, NO_COLOR) "erasing" would just leave a row of
        # spaces behind.
        if not self._line_open or not self.color:
            return
        self.write("\r\033[K")

    def width_of(self, text: str) -> int:
        plain, i = [], 0
        while i < len(text):
            if text[i] == "\033":
                j = text.find("m", i)
                if j == -1:
                    break
                i = j + 1
                continue
            plain.append(text[i])
            i += 1
        return len("".join(plain))

    def pad(self, text: str, width: int) -> str:
        return text + " " * max(0, width - self.width_of(text))

    def truncate(self, text: str, width: int) -> str:
        text = text.replace("\n", " ")
        if self.width_of(text) <= width:
            return text
        while self.width_of(text) > width - 1 and text:
            text = text[:-1]
        return text + "…"

    # --------------------------------------------------------------- chrome
    def title(self, text: str, subtitle: str = "") -> None:
        bar = "▌" if self.color else "|"
        self.out()
        self.out(self.paint(bar, "bcyan") + " " + self.paint(text, "bold", "bwhite"))
        if subtitle:
            self.out(self.paint(bar, "cyan") + " " + self.paint(subtitle, "grey"))
        self.out(self.paint("─" * self.width, "grey"))

    def heading(self, text: str) -> None:
        self.out()
        self.out(self.paint(f"{text}", "bold", "bcyan") + self.paint(" " + "─" * 2, "grey"))

    def rule(self) -> None:
        self.out(self.paint("─" * self.width, "grey"))

    def mark(self, kind: str, text: str) -> None:
        glyph, style = MARK[kind]
        self.out(f"{self.paint(glyph, style)} {text}")

    def ok(self, text: str) -> None:
        self.mark("ok", text)

    def warn(self, text: str) -> None:
        self.mark("warn", self.paint(text, "byellow"))

    def fail(self, text: str) -> None:
        self.mark("fail", self.paint(text, "bred"))

    def info(self, text: str) -> None:
        self.mark("info", self.paint(text, "bcyan"))

    def step(self, text: str) -> None:
        self.mark("step", self.paint(text, "grey"))

    def note(self, text: str) -> None:
        self.out("  " + self.paint(self.truncate(text, self.width - 2), "grey"))

    def lines(self, text: str) -> None:
        for line in str(text).splitlines() or [""]:
            self.out("  " + self.paint(line, "grey"))

    def status(self, kind: str, label: str, value: str, hint: str = "") -> None:
        """One dashboard row: colored state, label, value, optional hint."""
        glyph, style = MARK[kind]
        row = f"  {self.paint(glyph, style)} {self.paint(self.pad(label, 20), 'grey')} {value}"
        if hint:
            row += self.paint("  " + self.truncate(hint, 44), "grey")
        self.out(row)

    def table(self, headers: tuple[str, ...], rows: list[tuple], mark_col: int = -1) -> None:
        columns = len(headers)
        widths = [self.width_of(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row[:columns]):
                widths[i] = max(widths[i], self.width_of(str(cell)))
        budget = self.width - (3 * columns) - 2
        while sum(widths) > budget and max(widths) > 8:
            widths[widths.index(max(widths))] -= 1
        self.out("  " + self.paint("  ".join(self.pad(h.upper(), w) for h, w in zip(headers, widths)), "bold", "grey"))
        for row in rows:
            cells = []
            for i, cell in enumerate(row[:columns]):
                text = self.truncate(str(cell), widths[i])
                if i == mark_col:
                    glyph, style = MARK.get(str(cell).lower(), (" ", "grey"))
                    text = self.paint(glyph, style)
                cells.append(self.pad(text, widths[i]))
            self.out("  " + "  ".join(cells).rstrip())

    # -------------------------------------------------------------- spinner
    def spinner(self, text: str):
        return _Spinner(self, text)

    def progress(self, label: str, total: int = 0):
        return _Progress(self, label, total)

    # -------------------------------------------------------------- prompts
    def ask(self, label: str, default: str = "", hint: str = "", password: bool = False,
            allow_empty: bool = False) -> str:
        suffix = self.paint(f" ({default})", "grey") if default else ""
        extra = self.paint(f"  {hint}", "grey") if hint else ""
        while True:
            self.clear_line()
            self.write(f"{self.paint('?', 'bcyan')} {label}{suffix}{extra} ")
            try:
                import getpass

                raw = getpass.getpass("") if password else input("")
            except (EOFError, KeyboardInterrupt):
                self.out()
                raise
            value = raw.strip()
            if not value and default:
                return default
            if not value and allow_empty:
                return ""
            if value:
                return value
            self.warn("Bitte einen Wert eingeben (oder Strg+C zum Abbrechen).")

    def confirm(self, label: str, default: bool = True) -> bool:
        hint = "J/n" if default else "y/N"
        while True:
            self.clear_line()
            self.write(f"{self.paint('?', 'bcyan')} {label} " + self.paint(f"({hint})", "grey") + " ")
            answer = input("").strip().lower()
            if not answer:
                return default
            if answer in ("j", "ja", "y", "yes"):
                return True
            if answer in ("n", "nein", "no"):
                return False
            self.warn("Bitte j oder n eingeben.")

    def choose(self, label: str, options: list[tuple[str, str]], default: int = 0) -> int | None:
        """Arrow-key single-select. options = [(value, label), ...]. None when
        the user aborts with Esc/q. Falls back to numbered input when stdin
        isn't a terminal (piped output, CI)."""
        if not options:
            return None
        if not self.interactive:
            self.heading(label)
            self.table(("#", "Auswahl"), [(i + 1, text) for i, (_, text) in enumerate(options)])
            answer = self.ask("Nummer", str(default + 1))
            try:
                index = int(answer) - 1
            except ValueError:
                return None
            return index if 0 <= index < len(options) else None

        index = min(max(default, 0), len(options) - 1)
        while True:
            self.out()
            self.out("  " + self.paint(label, "bold", "bwhite"))
            for i, (_, text) in enumerate(options):
                if i == index:
                    self.out("  " + self.paint(" ▸ ", "bcyan") + self.paint(text, "bold"))
                else:
                    self.out("  " + self.paint("   " + text, "grey"))
            self.out("  " + self.paint("↑↓ auswählen · Enter bestätigen · Esc abbrechen", "grey"))
            key = read_key()
            if key in ("up", "k"):
                index = (index - 1) % len(options)
            elif key in ("down", "j"):
                index = (index + 1) % len(options)
            elif key == "home":
                index = 0
            elif key == "end":
                index = len(options) - 1
            elif key == "enter":
                return index
            elif key in ("esc", "ctrl-c", "q"):
                return None

    def menu(self, entries: list[tuple]) -> int | None:
        """Main menu. entries = [(key, label, hint), ...] — keys are also
        accepted as single letters/digits for scripted input."""
        options = [(str(i), f"{self.paint(e[1], 'bwhite')}  {self.paint(e[2], 'grey')}")
                   for i, e in enumerate(entries)]
        while True:
            self.out()
            for i, (_, text) in enumerate(options):
                self.out("  " + self.paint(f" {i + 1} ", "bold", "bcyan") + " " + text)
            self.out("  " + self.paint(" q ", "bold", "grey") + " " + self.paint("Beenden", "grey"))
            self.out("  " + self.paint("Nummer oder Kürzel eingeben", "grey"))
            self.clear_line()
            self.write(f"{self.paint('>', 'bcyan')} ")
            try:
                answer = input("").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if answer.isdigit() and 1 <= int(answer) <= len(entries):
                return int(answer) - 1
            if answer.lower() in ("q", "quit", "exit"):
                return None
            if answer:
                match = next((i for i, e in enumerate(entries) if str(e[0]) == answer.lower()), None)
                if match is not None:
                    return match
            if not self.interactive:
                self.fail("Keine gültige Auswahl.")
                return None

    def clear_screen(self) -> None:
        self._line_open = False
        if self.color and self.interactive:
            self.write("\033[2J\033[H")
        else:
            self.out()

    def pause(self, text: str = "Weiter mit Enter …") -> None:
        self.clear_line()
        self.out(self.paint(text, "grey"))
        try:
            input("")
        except (EOFError, KeyboardInterrupt):
            pass


class _Spinner:
    def __init__(self, ui: Ui, text: str) -> None:
        self.ui, self.text, self.stop_flag = ui, text, False
        self.thread: threading.Thread | None = None
        self.animated = ui.interactive and ui.color

    def _run(self) -> None:
        i, started = 0, time.monotonic()
        while not self.stop_flag:
            elapsed = time.monotonic() - started
            frame = self.ui.frames[i % len(self.ui.frames)]
            self.ui.write("\r\033[K")
            line = f"{self.ui.paint(frame, 'bcyan')} {self.text} {self.ui.paint(f'({elapsed:.0f}s)', 'grey')}"
            self.ui.write(self.ui.pad(line, self.ui.width - 1))
            i += 1
            time.sleep(0.1)

    def __enter__(self) -> "_Spinner":
        if not self.animated:
            # Piped output or no color: a static line beats a flickering one.
            self.ui.out(self.ui.paint("… " + self.text, "grey"))
            return self
        self.ui._busy = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def update(self, text: str) -> None:
        self.text = text

    def __exit__(self, *exc) -> None:
        self.stop_flag = True
        if self.thread:
            self.thread.join(timeout=1)
        self.ui._busy = False
        if not self.animated:
            return
        if exc[0] is None:
            self.ui.clear_line()
        else:
            self.ui.write("\n")


class _Progress:
    def __init__(self, ui: Ui, label: str, total: int) -> None:
        self.ui, self.label, self.total, self.done = ui, label, total, 0
        self.animated = ui.interactive and ui.color
        self._last = 0.0

    def _draw(self) -> None:
        if not self.animated:
            return
        now = time.monotonic()
        if now - self._last < 0.05:
            return
        self._last = now
        percent = f"{self.done / self.total * 100:3.0f}%" if self.total else ""
        filled = int(24 * (self.done / self.total)) if self.total else 0
        bar = "█" * filled + "░" * (24 - filled)
        line = (f"  {self.ui.paint(bar, 'bcyan')} {self.ui.paint(percent, 'grey')}  "
                f"{self.ui.paint(self.label, 'grey')}")
        self.ui.write("\r\033[K")
        self.ui.write(self.ui.pad(line, self.ui.width - 1))

    def advance(self, amount: int = 1) -> None:
        self.done += amount
        self._draw()

    def set(self, done: int, label: str = "") -> None:
        self.done = done
        if label:
            self.label = label
        self._draw()

    def finish(self, label: str = "") -> None:
        if label:
            self.label = label
        if self.total:
            self.done = self.total
            self._draw()
        if self.animated:
            self.ui.clear_line()
        else:
            # Piped output or no color: one summary line beats a frozen bar.
            self.ui.out(f"  {self.ui.paint('✓', 'bgreen')} {self.label}")

    def __enter__(self) -> "_Progress":
        return self

    def __exit__(self, *exc) -> None:
        self.ui.clear_line()


ui = Ui()
