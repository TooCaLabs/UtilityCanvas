#!/usr/bin/env python3
from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox

LOG_DIR = Path.home() / "Library" / "Logs" / "VocalCanvas"
LOG_FILE = LOG_DIR / "desktop.log"

# User-provided dark palette
BG = "#00113e"
SURFACE = "#00726d"
CARD = "#000072"
TEXT_PRIMARY = "#ececec"
TEXT_SECONDARY = "#b6b6b6"
ACCENT = "#001d29"
BORDER = "#00739e"
SUCCESS = "#0565a4"
WARNING = "#abac0d"
ERROR = "#ac0d0d"

CARD_TOP = "#0565a4"
CARD_BOTTOM = "#003a66"
CARD_INNER = "#001d29"
FIELD_BG = "#002851"
SHADOW_COLOR = "#000000"

BTN_TOP = "#0b85c8"
BTN_BOTTOM = "#0565a4"
BTN_BORDER = "#2aa5d6"

TAB_ACTIVE_TOP = "#0b85c8"
TAB_ACTIVE_BOTTOM = "#0565a4"
TAB_ACTIVE_BORDER = "#2aa5d6"
TAB_INACTIVE_TOP = "#00395c"
TAB_INACTIVE_BOTTOM = "#002743"
TAB_INACTIVE_BORDER = "#006791"

DEFAULT_TEXT = (
    "Download Vocal-Canvas today, this is made to help content creators use "
    "TextToSpeech easily in their videos!"
)
MIN_RATE = 80
MAX_RATE = 400


def log_line(message: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"{message}\n")
    except Exception:
        # Avoid crashing while trying to write diagnostics.
        pass


def log_exception(context: str, exc: Exception) -> None:
    log_line(f"[{context}] {exc}")
    log_line("".join(traceback.format_exception(exc)))


def show_startup_error(title: str, body: str) -> None:
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, body)
        root.destroy()
    except Exception:
        pass


def resolve_tool(tool_name: str) -> str:
    discovered = shutil.which(tool_name)
    if discovered:
        return discovered

    fallback = Path("/usr/bin") / tool_name
    if fallback.exists():
        return str(fallback)

    return ""


def discover_tools() -> dict[str, str]:
    tools: dict[str, str] = {}
    missing: list[str] = []

    for name in ("say", "afconvert", "afplay"):
        path = resolve_tool(name)
        if path:
            tools[name] = path
        else:
            missing.append(name)

    if missing:
        raise RuntimeError(
            f"Missing required macOS command(s): {', '.join(missing)}\n"
            f"Check {LOG_FILE} for details."
        )

    return tools


def parse_voices(say_cmd: str) -> list[str]:
    output = subprocess.check_output([say_cmd, "-v", "?"], text=True)
    voices: list[str] = []
    for line in output.splitlines():
        line = line.rstrip()
        if not line:
            continue
        # Typical format: "<voice name> <locale> # sample text"
        # Spacing can vary, so parse defensively.
        match = re.match(r"^(.*?)\s+\S+\s+#", line)
        if match:
            voice_name = match.group(1).strip()
        else:
            parts = re.split(r"\s{2,}", line, maxsplit=2)
            voice_name = parts[0].strip() if parts else ""

        if voice_name and voice_name not in voices:
            voices.append(voice_name)
    return voices


def render_wav(text: str, voice: str, rate: int, output_path: Path, say_cmd: str, afconvert_cmd: str) -> None:
    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        subprocess.run(
            [say_cmd, "-v", voice, "-r", str(rate), text, "-o", str(temp_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [afconvert_cmd, str(temp_path), str(output_path), "-f", "WAVE", "-d", "LEI16"],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        temp_path.unlink(missing_ok=True)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    if len(value) != 6:
        return (0, 0, 0)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{max(0, min(255, int(rgb[0]))):02x}{max(0, min(255, int(rgb[1]))):02x}{max(0, min(255, int(rgb[2]))):02x}"


def _blend(color_a: str, color_b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    a = _hex_to_rgb(color_a)
    b = _hex_to_rgb(color_b)
    mixed = (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )
    return _rgb_to_hex(mixed)


def _rounded_inset(y: int, height: int, radius: int) -> float:
    if radius <= 0:
        return 0.0

    lower_bound = height - radius
    if y < radius:
        dy = radius - y
    elif y > lower_bound:
        dy = y - lower_bound
    else:
        return 0.0

    inside = max(0.0, float(radius * radius - dy * dy))
    return float(radius - math.sqrt(inside))


def _draw_rounded_outline(
    canvas: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
    color: str,
    width: int,
    tag: str,
) -> None:
    if width <= 0:
        return

    if radius <= 0:
        canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=width, tags=tag)
        return

    r = radius
    canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style="arc", outline=color, width=width, tags=tag)
    canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style="arc", outline=color, width=width, tags=tag)
    canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style="arc", outline=color, width=width, tags=tag)
    canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style="arc", outline=color, width=width, tags=tag)

    canvas.create_line(x1 + r, y1, x2 - r, y1, fill=color, width=width, tags=tag)
    canvas.create_line(x2, y1 + r, x2, y2 - r, fill=color, width=width, tags=tag)
    canvas.create_line(x1 + r, y2, x2 - r, y2, fill=color, width=width, tags=tag)
    canvas.create_line(x1, y1 + r, x1, y2 - r, fill=color, width=width, tags=tag)


def _draw_rounded_vertical_gradient(
    canvas: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
    top_color: str,
    bottom_color: str,
    border_color: str,
    border_width: int,
    tag: str,
) -> None:
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)
    r = int(max(0, min(radius, width // 2, height // 2)))

    for row, y in enumerate(range(y1, y2 + 1)):
        t = row / max(1, height)
        color = _blend(top_color, bottom_color, t)
        inset = _rounded_inset(row, height, r)
        start_x = x1 + int(inset)
        end_x = x2 - int(inset)
        if end_x >= start_x:
            canvas.create_line(start_x, y, end_x, y, fill=color, tags=tag)

    _draw_rounded_outline(canvas, x1, y1, x2, y2, r, border_color, border_width, tag)


class RoundedGradientCard(tk.Canvas):
    def __init__(
        self,
        master: tk.Widget,
        *,
        radius: int,
        top_color: str,
        bottom_color: str,
        border_color: str,
        content_bg: str,
        padding: int,
        shadow_offset: int = 0,
        shadow_color: str = SHADOW_COLOR,
    ) -> None:
        super().__init__(master, highlightthickness=0, bd=0, relief="flat", bg=master.cget("bg"))
        self.radius = radius
        self.top_color = top_color
        self.bottom_color = bottom_color
        self.border_color = border_color
        self.padding = padding
        self.shadow_offset = max(0, shadow_offset)
        self.shadow_color = shadow_color

        self.content = tk.Frame(self, bg=content_bg)
        self._content_item = self.create_window(padding, padding, anchor="nw", window=self.content)

        self.bind("<Configure>", self._on_resize)
        self.after_idle(self._redraw)

    def _on_resize(self, _event: tk.Event) -> None:
        self._redraw()

    def _redraw(self) -> None:
        self.delete("card")

        width = self.winfo_width()
        height = self.winfo_height()
        if width < 8 or height < 8:
            return

        x1 = 1
        y1 = 1
        x2 = width - 2 - self.shadow_offset
        y2 = height - 2 - self.shadow_offset
        if x2 <= x1 + 2 or y2 <= y1 + 2:
            return

        if self.shadow_offset > 0:
            _draw_rounded_vertical_gradient(
                self,
                x1 + self.shadow_offset,
                y1 + self.shadow_offset,
                x2 + self.shadow_offset,
                y2 + self.shadow_offset,
                self.radius,
                self.shadow_color,
                self.shadow_color,
                self.shadow_color,
                0,
                "card",
            )

        _draw_rounded_vertical_gradient(
            self,
            x1,
            y1,
            x2,
            y2,
            self.radius,
            self.top_color,
            self.bottom_color,
            self.border_color,
            1,
            "card",
        )

        self.coords(self._content_item, x1 + self.padding, y1 + self.padding)
        self.itemconfigure(self._content_item, width=max(1, (x2 - x1 + 1) - (self.padding * 2)))


class RoundedGradientButton(tk.Canvas):
    def __init__(
        self,
        master: tk.Widget,
        *,
        text: str,
        command,
        top_color: str,
        bottom_color: str,
        border_color: str,
        text_color: str,
        radius: int = 12,
        height: int = 42,
        font: tuple[str, int, str] | tuple[str, int] = ("Avenir Next", 11, "bold"),
        shadow_offset: int = 2,
    ) -> None:
        super().__init__(
            master,
            height=height,
            highlightthickness=0,
            bd=0,
            relief="flat",
            bg=master.cget("bg"),
            cursor="hand2",
            takefocus=1,
        )

        self._label = text
        self._command = command
        self._top_color = top_color
        self._bottom_color = bottom_color
        self._border_color = border_color
        self._text_color = text_color
        self._radius = radius
        self._font = font
        self._shadow_offset = max(0, shadow_offset)

        self._enabled = True
        self._hovered = False
        self._pressed = False

        self.bind("<Configure>", self._on_resize)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<space>", self._on_keyboard_invoke)
        self.bind("<Return>", self._on_keyboard_invoke)

        self.after_idle(self._redraw)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._hovered = False
        self._pressed = False
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def set_palette(self, top_color: str, bottom_color: str, border_color: str, text_color: str | None = None) -> None:
        self._top_color = top_color
        self._bottom_color = bottom_color
        self._border_color = border_color
        if text_color is not None:
            self._text_color = text_color
        self._redraw()

    def _on_resize(self, _event: tk.Event) -> None:
        self._redraw()

    def _on_enter(self, _event: tk.Event) -> None:
        if not self._enabled:
            return
        self._hovered = True
        self._redraw()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hovered = False
        self._pressed = False
        self._redraw()

    def _on_press(self, event: tk.Event) -> None:
        if not self._enabled or event.num != 1:
            return
        self._pressed = True
        self._redraw()

    def _on_release(self, event: tk.Event) -> None:
        if not self._enabled:
            return

        was_pressed = self._pressed
        self._pressed = False
        self._redraw()

        if not was_pressed:
            return

        width = self.winfo_width()
        height = self.winfo_height()
        if 0 <= event.x <= width and 0 <= event.y <= height:
            self._command()

    def _on_keyboard_invoke(self, _event: tk.Event) -> str:
        if self._enabled:
            self._command()
        return "break"

    def _resolved_colors(self) -> tuple[str, str, str, str]:
        top = self._top_color
        bottom = self._bottom_color
        border = self._border_color
        text = self._text_color

        if not self._enabled:
            top = _blend(top, BG, 0.55)
            bottom = _blend(bottom, BG, 0.55)
            border = _blend(border, BG, 0.6)
            text = _blend(text, BG, 0.45)
        elif self._pressed:
            top = _blend(top, "#000000", 0.16)
            bottom = _blend(bottom, "#000000", 0.16)
        elif self._hovered:
            top = _blend(top, "#ffffff", 0.07)
            bottom = _blend(bottom, "#ffffff", 0.07)

        return top, bottom, border, text

    def _redraw(self) -> None:
        self.delete("btn")

        width = self.winfo_width()
        height = self.winfo_height()
        if width < 8 or height < 8:
            return

        top, bottom, border, text = self._resolved_colors()

        x1 = 1
        y1 = 1
        x2 = width - 2 - self._shadow_offset
        y2 = height - 2 - self._shadow_offset
        if x2 <= x1 + 2 or y2 <= y1 + 2:
            return

        if self._shadow_offset > 0:
            shadow = _blend(SHADOW_COLOR, BG, 0.35)
            _draw_rounded_vertical_gradient(
                self,
                x1 + self._shadow_offset,
                y1 + self._shadow_offset,
                x2 + self._shadow_offset,
                y2 + self._shadow_offset,
                self._radius,
                shadow,
                shadow,
                shadow,
                0,
                "btn",
            )

        _draw_rounded_vertical_gradient(
            self,
            x1,
            y1,
            x2,
            y2,
            self._radius,
            top,
            bottom,
            border,
            1,
            "btn",
        )

        y_offset = 1 if self._pressed and self._enabled else 0
        self.create_text(
            x1 + ((x2 - x1) // 2),
            y1 + ((y2 - y1) // 2) + y_offset,
            text=self._label,
            fill=text,
            font=self._font,
            tags="btn",
        )


class RoundedDropdown(tk.Canvas):
    def __init__(
        self,
        master: tk.Widget,
        *,
        variable: tk.StringVar,
        values: list[str] | None = None,
        radius: int = 12,
        height: int = 34,
        font: tuple[str, int] | tuple[str, int, str] = ("Avenir Next", 12),
        max_popup_rows: int = 10,
    ) -> None:
        super().__init__(
            master,
            height=height,
            highlightthickness=0,
            bd=0,
            relief="flat",
            bg=master.cget("bg"),
            cursor="hand2",
            takefocus=1,
        )

        self.variable = variable
        self.values = list(values or [])
        self.radius = radius
        self.font = font
        self.max_popup_rows = max(3, max_popup_rows)

        self._enabled = True
        self._hovered = False
        self._pressed = False
        self._popup: RoundedGradientCard | None = None
        self._listbox: tk.Listbox | None = None
        self._root_click_bindid: str | None = None

        self.variable.trace_add("write", lambda *_: self._redraw())

        self.bind("<Configure>", lambda _event: self._redraw())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Escape>", self._on_escape)
        self.bind("<Return>", self._on_keyboard_toggle)
        self.bind("<space>", self._on_keyboard_toggle)
        self.bind("<Down>", self._on_keyboard_toggle)
        self.bind("<Destroy>", self._on_destroy)

        self.after_idle(self._redraw)

    def set_values(self, values: list[str]) -> None:
        self.values = list(values)
        selected = self.variable.get().strip()
        if selected and selected not in self.values:
            self.variable.set("")
        self._refresh_listbox()
        self._redraw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._hovered = False
        self._pressed = False
        if not enabled:
            self.close_popup()
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def _on_destroy(self, _event: tk.Event) -> None:
        self.close_popup()

    def _on_press(self, event: tk.Event) -> None:
        if not self._enabled or event.num != 1:
            return
        self._pressed = True
        self.focus_set()
        self._redraw()

    def _on_release(self, event: tk.Event) -> None:
        if not self._enabled:
            return

        was_pressed = self._pressed
        self._pressed = False
        self._redraw()

        if not was_pressed:
            return

        width = self.winfo_width()
        height = self.winfo_height()
        if 0 <= event.x <= width and 0 <= event.y <= height:
            self._toggle_popup()

    def _on_enter(self, _event: tk.Event) -> None:
        if not self._enabled:
            return
        self._hovered = True
        self._redraw()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hovered = False
        self._pressed = False
        self._redraw()

    def _on_escape(self, _event: tk.Event) -> str:
        self.close_popup()
        return "break"

    def _on_keyboard_toggle(self, _event: tk.Event) -> str:
        if self._enabled:
            self._toggle_popup()
        return "break"

    def _resolved_colors(self) -> tuple[str, str, str, str]:
        top = _blend(FIELD_BG, "#ffffff", 0.06)
        bottom = FIELD_BG
        border = BORDER
        text = TEXT_PRIMARY

        if not self._enabled:
            top = _blend(top, BG, 0.55)
            bottom = _blend(bottom, BG, 0.55)
            border = _blend(border, BG, 0.6)
            text = _blend(text, BG, 0.45)
        elif self._pressed:
            top = _blend(top, "#000000", 0.15)
            bottom = _blend(bottom, "#000000", 0.15)
        elif self._popup is not None:
            top = _blend(top, "#ffffff", 0.06)
            border = _blend(BTN_BORDER, "#ffffff", 0.1)
        elif self._hovered:
            top = _blend(top, "#ffffff", 0.04)
            border = _blend(border, "#ffffff", 0.08)

        return top, bottom, border, text

    def _truncate_text(self, text: str, width_px: int) -> str:
        approx_char_px = 9
        max_chars = max(4, width_px // approx_char_px)
        if len(text) <= max_chars:
            return text
        return f"{text[: max_chars - 1]}…"

    def _redraw(self) -> None:
        self.delete("dropdown")

        width = self.winfo_width()
        height = self.winfo_height()
        if width < 16 or height < 16:
            return

        top, bottom, border, text_color = self._resolved_colors()

        x1 = 1
        y1 = 1
        shadow_offset = 2
        x2 = width - 2 - shadow_offset
        y2 = height - 2 - shadow_offset

        if x2 <= x1 + 2 or y2 <= y1 + 2:
            return

        shadow = _blend(SHADOW_COLOR, BG, 0.35)
        _draw_rounded_vertical_gradient(
            self,
            x1 + shadow_offset,
            y1 + shadow_offset,
            x2 + shadow_offset,
            y2 + shadow_offset,
            self.radius,
            shadow,
            shadow,
            shadow,
            0,
            "dropdown",
        )

        _draw_rounded_vertical_gradient(
            self,
            x1,
            y1,
            x2,
            y2,
            self.radius,
            top,
            bottom,
            border,
            1,
            "dropdown",
        )

        center_y = y1 + ((y2 - y1) // 2)
        arrow_x = x2 - 14
        arrow_color = text_color if self._enabled else _blend(TEXT_SECONDARY, BG, 0.45)

        self.create_line(
            x2 - 26,
            y1 + 7,
            x2 - 26,
            y2 - 7,
            fill=_blend(border, BG, 0.25),
            width=1,
            tags="dropdown",
        )
        self.create_polygon(
            arrow_x - 5,
            center_y - 2,
            arrow_x + 5,
            center_y - 2,
            arrow_x,
            center_y + 4,
            fill=arrow_color,
            outline=arrow_color,
            tags="dropdown",
        )

        value = self.variable.get().strip()
        display = value if value else "Select voice"
        display_color = text_color if value else _blend(TEXT_SECONDARY, BG, 0.12)
        display = self._truncate_text(display, max(40, (x2 - x1) - 42))

        self.create_text(
            x1 + 12,
            center_y,
            text=display,
            fill=display_color,
            font=self.font,
            anchor="w",
            tags="dropdown",
        )

    def _toggle_popup(self) -> None:
        if self._popup is not None:
            self.close_popup()
        else:
            self._open_popup()

    def _open_popup(self) -> None:
        if not self._enabled or not self.values or self._popup is not None:
            return

        host = self.winfo_toplevel()
        host.update_idletasks()

        width = max(260, self.winfo_width())
        rows = min(self.max_popup_rows, max(1, len(self.values)))
        popup_height = (rows * 28) + 16
        x = self.winfo_rootx() - host.winfo_rootx()
        y = self.winfo_rooty() - host.winfo_rooty() + self.winfo_height() + 4

        if y + popup_height > host.winfo_height() - 8:
            y = max(8, self.winfo_rooty() - host.winfo_rooty() - popup_height - 4)
        if x + width > host.winfo_width() - 8:
            x = max(8, host.winfo_width() - width - 8)
        if x < 8:
            x = 8

        shell = RoundedGradientCard(
            host,
            radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.07),
            bottom_color=FIELD_BG,
            border_color=BORDER,
            content_bg=FIELD_BG,
            padding=6,
            shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35),
        )
        shell.place(x=x, y=y, width=width, height=popup_height)
        shell.tk.call("raise", shell._w)

        inner = shell.content
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_rowconfigure(0, weight=1)

        listbox = tk.Listbox(
            inner,
            bd=0,
            highlightthickness=0,
            relief="flat",
            bg=FIELD_BG,
            fg=TEXT_PRIMARY,
            selectbackground=BTN_TOP,
            selectforeground=TEXT_PRIMARY,
            activestyle="none",
            font=("Avenir Next", 12),
            exportselection=False,
        )
        listbox.grid(row=0, column=0, sticky="nsew")

        scrollbar = tk.Scrollbar(
            inner,
            orient="vertical",
            command=listbox.yview,
            bd=0,
            highlightthickness=0,
            relief="flat",
            background=_blend(FIELD_BG, "#ffffff", 0.12),
            activebackground=BTN_TOP,
            troughcolor=_blend(FIELD_BG, BG, 0.16),
        )
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        listbox.configure(yscrollcommand=scrollbar.set)

        for voice in self.values:
            listbox.insert("end", voice)

        selected = self.variable.get().strip()
        if selected in self.values:
            index = self.values.index(selected)
            listbox.selection_set(index)
            listbox.activate(index)
        # Always open from top so the full range is obvious.
        listbox.yview_moveto(0.0)

        listbox.bind("<ButtonRelease-1>", self._on_listbox_select)
        listbox.bind("<Double-Button-1>", self._on_listbox_select)
        listbox.bind("<Return>", self._on_listbox_select)
        listbox.bind("<Escape>", self._on_listbox_escape)
        listbox.bind("<Motion>", self._on_listbox_hover)

        self._popup = shell
        self._listbox = listbox
        self._root_click_bindid = host.bind("<Button-1>", self._on_root_click, add="+")
        listbox.focus_set()
        self._redraw()

    def _refresh_listbox(self) -> None:
        if self._listbox is None:
            return
        self._listbox.delete(0, "end")
        for voice in self.values:
            self._listbox.insert("end", voice)

    def _on_listbox_hover(self, event: tk.Event) -> None:
        if self._listbox is None:
            return
        index = self._listbox.nearest(event.y)
        self._listbox.selection_clear(0, "end")
        self._listbox.selection_set(index)
        self._listbox.activate(index)

    def _on_listbox_escape(self, _event: tk.Event) -> str:
        self.close_popup()
        return "break"

    def _on_listbox_select(self, event: tk.Event) -> str:
        if self._listbox is None:
            self.close_popup()
            return "break"

        if self._listbox.curselection():
            index = int(self._listbox.curselection()[0])
        elif hasattr(event, "y"):
            index = int(self._listbox.nearest(event.y))
        else:
            self.close_popup()
            return "break"

        if 0 <= index < len(self.values):
            self.variable.set(self.values[index])

        self.close_popup()
        return "break"

    def _widget_is_child_of(self, widget: tk.Widget, parent: tk.Widget) -> bool:
        current: tk.Widget | None = widget
        while current is not None:
            if current == parent:
                return True
            current = getattr(current, "master", None)
        return False

    def _on_root_click(self, event: tk.Event) -> None:
        if self._popup is None:
            return

        if self._widget_is_child_of(event.widget, self):
            return
        if self._widget_is_child_of(event.widget, self._popup):
            return

        self.close_popup()

    def close_popup(self) -> None:
        if self._popup is not None:
            try:
                self._popup.destroy()
            except Exception:
                pass
        self._popup = None
        self._listbox = None

        if self._root_click_bindid is not None:
            try:
                self.winfo_toplevel().unbind("<Button-1>", self._root_click_bindid)
            except Exception:
                pass
        self._root_click_bindid = None
        if self.winfo_exists():
            self._redraw()


class RoundedSlider(tk.Canvas):
    def __init__(
        self,
        master: tk.Widget,
        *,
        variable: tk.IntVar,
        min_value: int,
        max_value: int,
        height: int = 30,
    ) -> None:
        super().__init__(
            master,
            height=height,
            highlightthickness=0,
            bd=0,
            relief="flat",
            bg=master.cget("bg"),
            cursor="hand2",
        )

        self.variable = variable
        self.min_value = min_value
        self.max_value = max_value
        self._enabled = True
        self._dragging = False

        self.variable.trace_add("write", lambda *_: self._redraw())

        self.bind("<Configure>", lambda _event: self._redraw())
        self.bind("<Button-1>", self._on_pointer_down)
        self.bind("<B1-Motion>", self._on_pointer_move)
        self.bind("<ButtonRelease-1>", self._on_pointer_up)

        self.after_idle(self._redraw)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._dragging = False
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def _track_bounds(self) -> tuple[int, int, int, int]:
        width = max(30, self.winfo_width())
        height = max(20, self.winfo_height())
        left = 12
        right = max(left + 1, width - 12)
        track_height = 10
        y1 = (height - track_height) // 2
        y2 = y1 + track_height
        return left, right, y1, y2

    def _clamp_value(self, value: int) -> int:
        return max(self.min_value, min(self.max_value, int(value)))

    def _value_to_x(self, value: int) -> int:
        left, right, _, _ = self._track_bounds()
        span = max(1, self.max_value - self.min_value)
        ratio = (self._clamp_value(value) - self.min_value) / span
        return left + int((right - left) * ratio)

    def _x_to_value(self, x: int) -> int:
        left, right, _, _ = self._track_bounds()
        ratio = (x - left) / max(1, right - left)
        value = self.min_value + round(max(0.0, min(1.0, ratio)) * (self.max_value - self.min_value))
        return self._clamp_value(value)

    def _set_from_x(self, x: int) -> None:
        if not self._enabled:
            return
        new_value = self._x_to_value(x)
        if new_value != self.variable.get():
            self.variable.set(new_value)
        else:
            self._redraw()

    def _on_pointer_down(self, event: tk.Event) -> None:
        if not self._enabled:
            return
        self._dragging = True
        self._set_from_x(event.x)

    def _on_pointer_move(self, event: tk.Event) -> None:
        if not self._enabled or not self._dragging:
            return
        self._set_from_x(event.x)

    def _on_pointer_up(self, _event: tk.Event) -> None:
        self._dragging = False

    def _redraw(self) -> None:
        self.delete("slider")

        width = self.winfo_width()
        height = self.winfo_height()
        if width < 30 or height < 14:
            return

        value = self._clamp_value(self.variable.get())
        left, right, y1, y2 = self._track_bounds()
        radius = (y2 - y1) // 2

        shadow = _blend(SHADOW_COLOR, BG, 0.35)
        _draw_rounded_vertical_gradient(
            self,
            left + 1,
            y1 + 2,
            right + 1,
            y2 + 2,
            radius,
            shadow,
            shadow,
            shadow,
            0,
            "slider",
        )

        track_top = _blend(FIELD_BG, "#ffffff", 0.04)
        track_bottom = FIELD_BG
        track_border = _blend(BORDER, BG, 0.25)
        _draw_rounded_vertical_gradient(
            self,
            left,
            y1,
            right,
            y2,
            radius,
            track_top,
            track_bottom,
            track_border,
            1,
            "slider",
        )

        value_x = self._value_to_x(value)
        fill_right = max(left + radius, value_x)
        _draw_rounded_vertical_gradient(
            self,
            left,
            y1,
            fill_right,
            y2,
            radius,
            BTN_TOP,
            BTN_BOTTOM,
            BTN_BORDER,
            0,
            "slider",
        )

        thumb_radius = 8
        cx = value_x
        cy = (y1 + y2) // 2
        thumb_fill = TEXT_PRIMARY if self._enabled else _blend(TEXT_PRIMARY, BG, 0.4)
        thumb_border = BTN_BORDER if self._enabled else _blend(BTN_BORDER, BG, 0.5)

        self.create_oval(
            cx - thumb_radius,
            cy - thumb_radius,
            cx + thumb_radius,
            cy + thumb_radius,
            fill=thumb_fill,
            outline=thumb_border,
            width=1,
            tags="slider",
        )


class DesktopApp(tk.Tk):
    def __init__(self, tool_paths: dict[str, str]) -> None:
        super().__init__()

        self.say_cmd = tool_paths["say"]
        self.afconvert_cmd = tool_paths["afconvert"]
        self.afplay_cmd = tool_paths["afplay"]

        self.title("Vocal Canvas")
        self.geometry("980x710")
        self.minsize(860, 620)
        self.configure(bg=BG)

        self.preview_path = Path(tempfile.gettempdir()) / "vocal_canvas_preview.wav"
        self.player_process: subprocess.Popen | None = None

        self.voice_var = tk.StringVar()
        self.rate_var = tk.IntVar(value=170)
        self.char_count_var = tk.StringVar(value="0 characters")

        self.tab_buttons: dict[str, RoundedGradientButton] = {}
        self.pages: dict[str, tk.Frame] = {}

        self._build_ui()
        self._load_voices()
        self._update_char_count()
        self._set_tab("demo")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=24)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(3, weight=1)

        title = tk.Label(
            outer,
            text="Vocal Canvas",
            bg=BG,
            fg=TEXT_PRIMARY,
            font=("Avenir Next", 34, "bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = tk.Label(
            outer,
            text="Desktop text-to-speech studio with local voices, preview, and export.",
            bg=BG,
            fg=TEXT_SECONDARY,
            font=("Avenir Next", 13),
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(4, 14))

        tab_row = tk.Frame(outer, bg=BG)
        tab_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        tab_row.grid_columnconfigure(0, weight=1)
        tab_row.grid_columnconfigure(1, weight=1)
        tab_row.grid_columnconfigure(2, weight=1)

        tabs = [("home", "Home"), ("demo", "Studio"), ("qa", "Q&A")]
        for index, (key, label) in enumerate(tabs):
            tab_btn = RoundedGradientButton(
                tab_row,
                text=label,
                command=lambda tab_key=key: self._set_tab(tab_key),
                top_color=TAB_INACTIVE_TOP,
                bottom_color=TAB_INACTIVE_BOTTOM,
                border_color=TAB_INACTIVE_BORDER,
                text_color=TEXT_SECONDARY,
                radius=12,
                height=36,
                font=("Avenir Next", 10, "bold"),
                shadow_offset=1,
            )
            tab_btn.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0))
            self.tab_buttons[key] = tab_btn

        page_card = RoundedGradientCard(
            outer,
            radius=28,
            top_color=CARD_TOP,
            bottom_color=CARD_BOTTOM,
            border_color=BORDER,
            content_bg=CARD_INNER,
            padding=18,
            shadow_offset=4,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35),
        )
        page_card.grid(row=3, column=0, sticky="nsew")

        page_host = page_card.content
        page_host.grid_columnconfigure(0, weight=1)
        page_host.grid_rowconfigure(0, weight=1)

        self.pages["home"] = self._build_placeholder_page(
            page_host,
            heading="Vocal Canvas",
            version="v0.1.1 (Beta)",
            copy=(
                "The Home tab is still being expanded. More information and quick access "
                "features will be added in future updates."
            ),
        )
        self.pages["demo"] = self._build_demo_page(page_host)
        self.pages["qa"] = self._build_placeholder_page(
            page_host,
            heading="Vocal Canvas",
            version="v0.1.1 (Beta)",
            copy=(
                "The Q&A section is currently being expanded. Detailed answers and "
                "documentation will be available soon."
            ),
        )

        for frame in self.pages.values():
            frame.grid(row=0, column=0, sticky="nsew")

    def _build_placeholder_page(self, parent: tk.Widget, *, heading: str, version: str, copy: str) -> tk.Frame:
        frame = tk.Frame(parent, bg=CARD_INNER)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        holder = tk.Frame(frame, bg=CARD_INNER)
        holder.grid(row=0, column=0, sticky="nsew")

        tk.Label(
            holder,
            text=heading,
            bg=CARD_INNER,
            fg=TEXT_PRIMARY,
            font=("Avenir Next", 24, "bold"),
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            holder,
            text=version,
            bg=CARD_INNER,
            fg=TEXT_PRIMARY,
            font=("Avenir Next", 14, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

        if copy:
            tk.Label(
                holder,
                text=copy,
                bg=CARD_INNER,
                fg=TEXT_SECONDARY,
                font=("Avenir Next", 12),
                anchor="w",
                justify="left",
                wraplength=760,
            ).pack(anchor="w", pady=(10, 0))

        return frame

    def _build_demo_page(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=CARD_INNER)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        tk.Label(frame, text="Script", bg=CARD_INNER, fg=TEXT_PRIMARY, font=("Avenir Next", 12, "bold")).grid(
            row=0, column=0, sticky="w", pady=(2, 6)
        )

        text_shell = RoundedGradientCard(
            frame,
            radius=16,
            top_color=_blend(FIELD_BG, "#ffffff", 0.07),
            bottom_color=FIELD_BG,
            border_color=BORDER,
            content_bg=FIELD_BG,
            padding=1,
            shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35),
        )
        text_shell.grid(row=1, column=0, sticky="nsew")
        text_shell.content.grid_columnconfigure(0, weight=1)
        text_shell.content.grid_rowconfigure(0, weight=1)

        self.text_box = tk.Text(
            text_shell.content,
            wrap="word",
            height=11,
            bd=0,
            highlightthickness=0,
            font=("Avenir Next", 13),
            padx=12,
            pady=10,
            bg=FIELD_BG,
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief="flat",
        )
        self.text_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.text_box.insert("1.0", DEFAULT_TEXT)
        self.text_box.bind("<KeyRelease>", lambda _event: self._update_char_count())

        meta_row = tk.Frame(frame, bg=CARD_INNER)
        meta_row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        meta_row.grid_columnconfigure(0, weight=1)

        self.char_count_label = tk.Label(
            meta_row,
            textvariable=self.char_count_var,
            bg=CARD_INNER,
            fg=TEXT_SECONDARY,
            font=("Avenir Next", 10, "bold"),
            anchor="e",
        )
        self.char_count_label.grid(row=0, column=0, sticky="e")

        controls = tk.Frame(frame, bg=CARD_INNER)
        controls.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        controls.grid_columnconfigure(0, weight=1)
        controls.grid_columnconfigure(1, weight=1)

        tk.Label(controls, text="Voice", bg=CARD_INNER, fg=TEXT_PRIMARY, font=("Avenir Next", 11, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(controls, text="Speed", bg=CARD_INNER, fg=TEXT_PRIMARY, font=("Avenir Next", 11, "bold")).grid(
            row=0, column=1, sticky="w"
        )

        voice_shell = RoundedGradientCard(
            controls,
            radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.06),
            bottom_color=FIELD_BG,
            border_color=BORDER,
            content_bg=FIELD_BG,
            padding=2,
            shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35),
        )
        voice_shell.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(4, 0))
        voice_shell.configure(height=44)
        voice_shell.content.grid_columnconfigure(0, weight=1)

        self.voice_combo = RoundedDropdown(
            voice_shell.content,
            variable=self.voice_var,
            values=[],
            radius=10,
            height=34,
            font=("Avenir Next", 12),
            max_popup_rows=11,
        )
        self.voice_combo.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        speed_shell = RoundedGradientCard(
            controls,
            radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.06),
            bottom_color=FIELD_BG,
            border_color=BORDER,
            content_bg=FIELD_BG,
            padding=4,
            shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35),
        )
        speed_shell.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        speed_shell.configure(height=44)
        speed_shell.content.grid_columnconfigure(0, weight=1)

        speed_row = tk.Frame(speed_shell.content, bg=FIELD_BG)
        speed_row.grid(row=0, column=0, sticky="ew")
        speed_row.grid_columnconfigure(0, weight=1)

        self.rate_slider = RoundedSlider(
            speed_row,
            variable=self.rate_var,
            min_value=MIN_RATE,
            max_value=MAX_RATE,
            height=30,
        )
        self.rate_slider.grid(row=0, column=0, sticky="ew")

        self.rate_label = tk.Label(
            speed_row,
            text=str(self.rate_var.get()),
            bg=FIELD_BG,
            fg=TEXT_SECONDARY,
            font=("Avenir Next", 10, "bold"),
        )
        self.rate_label.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.rate_var.trace_add("write", lambda *_: self.rate_label.config(text=str(self.rate_var.get())))

        self.generate_btn = RoundedGradientButton(
            frame,
            text="Generate Audio",
            command=self.preview_audio,
            top_color=BTN_TOP,
            bottom_color=BTN_BOTTOM,
            border_color=BTN_BORDER,
            text_color=TEXT_PRIMARY,
            radius=14,
            height=46,
            font=("Avenir Next", 12, "bold"),
            shadow_offset=2,
        )
        self.generate_btn.grid(row=4, column=0, sticky="ew", pady=(12, 0))

        action_row = tk.Frame(frame, bg=CARD_INNER)
        action_row.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        action_row.grid_columnconfigure(0, weight=1)
        action_row.grid_columnconfigure(1, weight=1)

        self.export_btn = RoundedGradientButton(
            action_row,
            text="Export WAV",
            command=self.export_audio,
            top_color=BTN_TOP,
            bottom_color=BTN_BOTTOM,
            border_color=BTN_BORDER,
            text_color=TEXT_PRIMARY,
            radius=12,
            height=40,
            font=("Avenir Next", 11, "bold"),
            shadow_offset=2,
        )
        self.export_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.clear_btn = RoundedGradientButton(
            action_row,
            text="Clear",
            command=self.clear_text,
            top_color=BTN_TOP,
            bottom_color=BTN_BOTTOM,
            border_color=BTN_BORDER,
            text_color=TEXT_PRIMARY,
            radius=12,
            height=40,
            font=("Avenir Next", 11, "bold"),
            shadow_offset=2,
        )
        self.clear_btn.grid(row=0, column=1, sticky="ew")

        self.status = tk.Label(
            frame,
            text="Ready.",
            bg=CARD_INNER,
            fg=TEXT_SECONDARY,
            font=("Avenir Next", 10, "bold"),
            anchor="w",
        )
        self.status.grid(row=6, column=0, sticky="ew", pady=(10, 2))

        return frame

    def _set_tab(self, tab_name: str) -> None:
        if tab_name not in self.pages:
            return

        self.pages[tab_name].tkraise()

        for key, button in self.tab_buttons.items():
            if key == tab_name:
                button.set_palette(TAB_ACTIVE_TOP, TAB_ACTIVE_BOTTOM, TAB_ACTIVE_BORDER, TEXT_PRIMARY)
            else:
                button.set_palette(TAB_INACTIVE_TOP, TAB_INACTIVE_BOTTOM, TAB_INACTIVE_BORDER, TEXT_SECONDARY)

    def _load_voices(self) -> None:
        try:
            voices = parse_voices(self.say_cmd)
        except Exception as exc:
            log_exception("Failed loading voices", exc)
            messagebox.showerror("Voices", f"Unable to load voices.\n\nLog: {LOG_FILE}")
            voices = []

        self.voice_combo.set_values(voices)

        if "Samantha" in voices:
            self.voice_var.set("Samantha")
        elif voices:
            self.voice_var.set(voices[0])
        else:
            self.voice_var.set("")
            self._set_status("No voices found.", "error")

    def _set_status(self, message: str, kind: str = "idle") -> None:
        color = TEXT_SECONDARY
        if kind == "success":
            color = SUCCESS
        elif kind == "error":
            color = ERROR
        elif kind == "loading":
            color = WARNING

        self.status.config(text=message, fg=color)

    def _set_busy(self, busy: bool) -> None:
        enabled = not busy
        self.generate_btn.set_enabled(enabled)
        self.export_btn.set_enabled(enabled)
        self.clear_btn.set_enabled(enabled)
        self.rate_slider.set_enabled(enabled)
        self.voice_combo.set_enabled(enabled)

    def _update_char_count(self) -> None:
        count = len(self.text_box.get("1.0", "end").strip())
        suffix = "" if count == 1 else "s"
        self.char_count_var.set(f"{count} character{suffix}")

    def _collect_inputs(self) -> tuple[str, str, int] | None:
        text = self.text_box.get("1.0", "end").strip()
        voice = self.voice_var.get().strip()
        rate = int(self.rate_var.get())

        if not text:
            messagebox.showerror("Missing text", "Please enter text to convert.")
            return None
        if not voice:
            messagebox.showerror("Missing voice", "Please choose a voice.")
            return None
        if not MIN_RATE <= rate <= MAX_RATE:
            messagebox.showerror("Invalid speed", f"Speed must be between {MIN_RATE} and {MAX_RATE}.")
            return None

        return text, voice, rate

    def _play_file(self, path: Path) -> None:
        if self.player_process and self.player_process.poll() is None:
            self.player_process.terminate()

        self.player_process = subprocess.Popen([self.afplay_cmd, str(path)])

    def clear_text(self) -> None:
        self.text_box.delete("1.0", "end")
        self._update_char_count()
        self._set_status("Ready.")

    def preview_audio(self) -> None:
        payload = self._collect_inputs()
        if not payload:
            return

        text, voice, rate = payload
        self._set_busy(True)
        self._set_status("Generating preview...", "loading")
        self.update_idletasks()

        try:
            render_wav(
                text=text,
                voice=voice,
                rate=rate,
                output_path=self.preview_path,
                say_cmd=self.say_cmd,
                afconvert_cmd=self.afconvert_cmd,
            )
            self._play_file(self.preview_path)
            self._set_status(f"Preview playing with {voice} at {rate}.", "success")
        except Exception as exc:
            log_exception("Preview failed", exc)
            messagebox.showerror("Preview failed", f"Something went wrong.\n\nLog: {LOG_FILE}")
            self._set_status("Preview failed.", "error")
        finally:
            self._set_busy(False)

    def export_audio(self) -> None:
        payload = self._collect_inputs()
        if not payload:
            return

        text, voice, rate = payload
        save_path = filedialog.asksaveasfilename(
            title="Save speech as...",
            defaultextension=".wav",
            initialfile="vocal_canvas.wav",
            filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")],
        )

        if not save_path:
            return

        output = Path(save_path)
        self._set_busy(True)
        self._set_status("Exporting file...", "loading")
        self.update_idletasks()

        try:
            render_wav(
                text=text,
                voice=voice,
                rate=rate,
                output_path=output,
                say_cmd=self.say_cmd,
                afconvert_cmd=self.afconvert_cmd,
            )
            self._set_status(f"Saved to {output.name}.", "success")
            messagebox.showinfo("Saved", f"Audio exported to:\n{output}")
        except Exception as exc:
            log_exception("Export failed", exc)
            messagebox.showerror("Export failed", f"Something went wrong.\n\nLog: {LOG_FILE}")
            self._set_status("Export failed.", "error")
        finally:
            self._set_busy(False)

    def _on_close(self) -> None:
        if self.player_process and self.player_process.poll() is None:
            self.player_process.terminate()
        self.voice_combo.close_popup()
        self.destroy()


def main() -> int:
    log_line("=== Vocal Canvas desktop launch ===")

    try:
        tool_paths = discover_tools()
        log_line(f"Tool paths: {tool_paths}")
    except Exception as exc:
        log_exception("Tool discovery", exc)
        show_startup_error("Vocal Canvas", f"Startup failed.\n\n{exc}")
        return 1

    try:
        app = DesktopApp(tool_paths)
        app.mainloop()
        return 0
    except Exception as exc:
        log_exception("Unhandled app exception", exc)
        show_startup_error("Vocal Canvas", f"The app crashed on startup.\n\nLog: {LOG_FILE}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
