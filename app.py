#!/usr/bin/env python3
from __future__ import annotations
import sys, subprocess

# ── auto-install dependencies when running from source (not inside .app) ──────
if not getattr(sys, "frozen", False):
    _DEPS = [
        ("numpy",         "numpy"),
        ("sounddevice",   "sounddevice"),
        ("faster_whisper","faster-whisper"),
    ]
    _missing = [pkg for mod, pkg in _DEPS if not __import__("importlib").util.find_spec(mod)]
    if _missing:
        print(f"Installing missing packages: {', '.join(_missing)} …")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", *_missing,
             "--break-system-packages", "-q"])
        print("Done. Starting app…\n")
    del _DEPS, _missing
# ─────────────────────────────────────────────────────────────────────────────

import math
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

LOG_DIR  = Path.home() / "Library" / "Logs" / "VocalCanvas"
LOG_FILE = LOG_DIR / "desktop.log"

# ── palette ───────────────────────────────────────────────────────────────────
BG             = "#00113e"
SURFACE        = "#00726d"
CARD           = "#000072"
TEXT_PRIMARY   = "#ececec"
TEXT_SECONDARY = "#b6b6b6"
ACCENT         = "#001d29"
BORDER         = "#00739e"
SUCCESS        = "#0565a4"
WARNING        = "#abac0d"
ERROR          = "#ac0d0d"

CARD_TOP    = "#0565a4"
CARD_BOTTOM = "#003a66"
CARD_INNER  = "#001d29"
FIELD_BG    = "#002851"
SHADOW_COLOR = "#000000"

BTN_TOP    = "#0b85c8"
BTN_BOTTOM = "#0565a4"
BTN_BORDER = "#2aa5d6"

TAB_ACTIVE_TOP      = "#0b85c8"
TAB_ACTIVE_BOTTOM   = "#0565a4"
TAB_ACTIVE_BORDER   = "#2aa5d6"
TAB_INACTIVE_TOP    = "#00395c"
TAB_INACTIVE_BOTTOM = "#002743"
TAB_INACTIVE_BORDER = "#006791"

DEFAULT_TEXT = (
    "Download Vocal-Canvas today, this is made to help content creators use "
    "TextToSpeech easily in their videos!"
)
MIN_RATE = 80
MAX_RATE = 400

# ── VC constants ──────────────────────────────────────────────────────────────
VC_RATE           = 16000
VC_CHUNK_N        = int(VC_RATE * 20 / 1000)   # 320 samples / 20 ms
VC_VOICE_ON_RMS   = 0.010
VC_VOICE_OFF_RMS  = 0.007
VC_PRE_ROLL       = 10    # chunks kept before speech onset
VC_SILENCE_CHUNKS = 28    # ~560 ms of silence → send to Whisper
VC_MIN_CHUNKS     = 8     # ignore blips < 160 ms
VC_MODEL_SIZES    = ["tiny", "base", "small"]


# ── logging ───────────────────────────────────────────────────────────────────

def log_line(message: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"{message}\n")
    except Exception:
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


# ── tool discovery ────────────────────────────────────────────────────────────

def resolve_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    fb = Path("/usr/bin") / name
    return str(fb) if fb.exists() else ""


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
        raise RuntimeError(f"Missing macOS command(s): {', '.join(missing)}")
    return tools


def parse_voices(say_cmd: str) -> list[str]:
    output = subprocess.check_output([say_cmd, "-v", "?"], text=True)
    voices: list[str] = []
    for line in output.splitlines():
        line = line.rstrip()
        if not line:
            continue
        match = re.match(r"^(.*?)\s+\S+\s+#", line)
        if match:
            name = match.group(1).strip()
        else:
            parts = re.split(r"\s{2,}", line, maxsplit=2)
            name = parts[0].strip() if parts else ""
        if name and name not in voices:
            voices.append(name)
    return voices


def render_wav(text: str, voice: str, rate: int, output_path: Path,
               say_cmd: str, afconvert_cmd: str) -> None:
    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tf:
        tmp = Path(tf.name)
    try:
        subprocess.run([say_cmd, "-v", voice, "-r", str(rate), text, "-o", str(tmp)],
                       check=True, capture_output=True, text=True)
        subprocess.run([afconvert_cmd, str(tmp), str(output_path), "-f", "WAVE", "-d", "LEI16"],
                       check=True, capture_output=True, text=True)
    finally:
        tmp.unlink(missing_ok=True)


# ── drawing helpers ───────────────────────────────────────────────────────────

def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    v = color.lstrip("#")
    if len(v) != 6:
        return (0, 0, 0)
    return tuple(int(v[i:i+2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{max(0,min(255,int(rgb[0]))):02x}{max(0,min(255,int(rgb[1]))):02x}{max(0,min(255,int(rgb[2]))):02x}"


def _blend(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    ra, ga, ba = _hex_to_rgb(a)
    rb, gb, bb = _hex_to_rgb(b)
    return _rgb_to_hex((int(ra+(rb-ra)*t), int(ga+(gb-ga)*t), int(ba+(bb-ba)*t)))


def _rounded_inset(y: int, height: int, radius: int) -> float:
    if radius <= 0:
        return 0.0
    lower = height - radius
    dy = (radius - y) if y < radius else (y - lower) if y > lower else 0
    if dy == 0:
        return 0.0
    return float(radius - math.sqrt(max(0.0, float(radius*radius - dy*dy))))


def _draw_rounded_outline(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int,
                           radius: int, color: str, width: int, tag: str) -> None:
    if width <= 0:
        return
    if radius <= 0:
        canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=width, tags=tag)
        return
    r = radius
    canvas.create_arc(x1, y1, x1+2*r, y1+2*r, start=90, extent=90, style="arc", outline=color, width=width, tags=tag)
    canvas.create_arc(x2-2*r, y1, x2, y1+2*r, start=0, extent=90, style="arc", outline=color, width=width, tags=tag)
    canvas.create_arc(x2-2*r, y2-2*r, x2, y2, start=270, extent=90, style="arc", outline=color, width=width, tags=tag)
    canvas.create_arc(x1, y2-2*r, x1+2*r, y2, start=180, extent=90, style="arc", outline=color, width=width, tags=tag)
    canvas.create_line(x1+r, y1, x2-r, y1, fill=color, width=width, tags=tag)
    canvas.create_line(x2, y1+r, x2, y2-r, fill=color, width=width, tags=tag)
    canvas.create_line(x1+r, y2, x2-r, y2, fill=color, width=width, tags=tag)
    canvas.create_line(x1, y1+r, x1, y2-r, fill=color, width=width, tags=tag)


def _draw_rounded_vertical_gradient(canvas: tk.Canvas, x1: int, y1: int,
                                     x2: int, y2: int, radius: int,
                                     top_color: str, bottom_color: str,
                                     border_color: str, border_width: int,
                                     tag: str) -> None:
    width  = max(1, x2 - x1)
    height = max(1, y2 - y1)
    r = int(max(0, min(radius, width // 2, height // 2)))
    for row, y in enumerate(range(y1, y2 + 1)):
        t     = row / max(1, height)
        color = _blend(top_color, bottom_color, t)
        inset = _rounded_inset(row, height, r)
        sx    = x1 + int(inset)
        ex    = x2 - int(inset)
        if ex >= sx:
            canvas.create_line(sx, y, ex, y, fill=color, tags=tag)
    _draw_rounded_outline(canvas, x1, y1, x2, y2, r, border_color, border_width, tag)


# ── widget classes ────────────────────────────────────────────────────────────

class RoundedGradientCard(tk.Canvas):
    def __init__(self, master: tk.Widget, *, radius: int, top_color: str,
                 bottom_color: str, border_color: str, content_bg: str,
                 padding: int, shadow_offset: int = 0,
                 shadow_color: str = SHADOW_COLOR) -> None:
        super().__init__(master, highlightthickness=0, bd=0, relief="flat",
                         bg=master.cget("bg"))
        self.radius       = radius
        self.top_color    = top_color
        self.bottom_color = bottom_color
        self.border_color = border_color
        self.padding      = padding
        self.shadow_offset = max(0, shadow_offset)
        self.shadow_color  = shadow_color
        self.content       = tk.Frame(self, bg=content_bg)
        self._content_item = self.create_window(padding, padding, anchor="nw",
                                                window=self.content)
        self.bind("<Configure>", self._on_resize)
        self.after_idle(self._redraw)

    def _on_resize(self, _event: tk.Event) -> None:
        self._redraw()

    def _redraw(self) -> None:
        self.delete("card")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 8 or h < 8:
            return
        x1, y1 = 1, 1
        x2, y2 = w - 2 - self.shadow_offset, h - 2 - self.shadow_offset
        if x2 <= x1 + 2 or y2 <= y1 + 2:
            return
        if self.shadow_offset > 0:
            _draw_rounded_vertical_gradient(self, x1+self.shadow_offset,
                y1+self.shadow_offset, x2+self.shadow_offset, y2+self.shadow_offset,
                self.radius, self.shadow_color, self.shadow_color, self.shadow_color,
                0, "card")
        _draw_rounded_vertical_gradient(self, x1, y1, x2, y2, self.radius,
            self.top_color, self.bottom_color, self.border_color, 1, "card")
        self.coords(self._content_item, x1 + self.padding, y1 + self.padding)
        self.itemconfigure(self._content_item,
                           width=max(1, (x2-x1+1) - self.padding*2))


class RoundedGradientButton(tk.Canvas):
    def __init__(self, master: tk.Widget, *, text: str, command,
                 top_color: str, bottom_color: str, border_color: str,
                 text_color: str, radius: int = 12, height: int = 42,
                 font: tuple = ("Avenir Next", 11, "bold"),
                 shadow_offset: int = 2) -> None:
        super().__init__(master, height=height, highlightthickness=0, bd=0,
                         relief="flat", bg=master.cget("bg"),
                         cursor="hand2", takefocus=1)
        self._label         = text
        self._command       = command
        self._top_color     = top_color
        self._bottom_color  = bottom_color
        self._border_color  = border_color
        self._text_color    = text_color
        self._radius        = radius
        self._font          = font
        self._shadow_offset = max(0, shadow_offset)
        self._enabled  = True
        self._hovered  = False
        self._pressed  = False
        self.bind("<Configure>",       self._on_resize)
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>",           self._on_enter)
        self.bind("<Leave>",           self._on_leave)
        self.bind("<space>",           self._on_keyboard_invoke)
        self.bind("<Return>",          self._on_keyboard_invoke)
        self.after_idle(self._redraw)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._hovered = False
        self._pressed = False
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def set_palette(self, top_color: str, bottom_color: str,
                    border_color: str, text_color: str | None = None) -> None:
        self._top_color    = top_color
        self._bottom_color = bottom_color
        self._border_color = border_color
        if text_color is not None:
            self._text_color = text_color
        self._redraw()

    def set_text(self, text: str) -> None:
        self._label = text
        self._redraw()

    def _on_resize(self, _e: tk.Event) -> None: self._redraw()
    def _on_enter(self, _e: tk.Event) -> None:
        if self._enabled: self._hovered = True; self._redraw()
    def _on_leave(self, _e: tk.Event) -> None:
        self._hovered = False; self._pressed = False; self._redraw()
    def _on_press(self, e: tk.Event) -> None:
        if self._enabled and e.num == 1: self._pressed = True; self._redraw()
    def _on_release(self, e: tk.Event) -> None:
        if not self._enabled: return
        was = self._pressed; self._pressed = False; self._redraw()
        if not was: return
        if 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self._command()
    def _on_keyboard_invoke(self, _e: tk.Event) -> str:
        if self._enabled: self._command()
        return "break"

    def _resolved_colors(self) -> tuple[str, str, str, str]:
        t, b, bo, tx = self._top_color, self._bottom_color, self._border_color, self._text_color
        if not self._enabled:
            t  = _blend(t, BG, 0.55); b  = _blend(b, BG, 0.55)
            bo = _blend(bo, BG, 0.6); tx = _blend(tx, BG, 0.45)
        elif self._pressed:
            t = _blend(t, "#000000", 0.16); b = _blend(b, "#000000", 0.16)
        elif self._hovered:
            t = _blend(t, "#ffffff", 0.07); b = _blend(b, "#ffffff", 0.07)
        return t, b, bo, tx

    def _redraw(self) -> None:
        self.delete("btn")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 8 or h < 8: return
        t, b, bo, tx = self._resolved_colors()
        x1, y1 = 1, 1
        x2, y2 = w - 2 - self._shadow_offset, h - 2 - self._shadow_offset
        if x2 <= x1+2 or y2 <= y1+2: return
        if self._shadow_offset > 0:
            sh = _blend(SHADOW_COLOR, BG, 0.35)
            _draw_rounded_vertical_gradient(self, x1+self._shadow_offset,
                y1+self._shadow_offset, x2+self._shadow_offset, y2+self._shadow_offset,
                self._radius, sh, sh, sh, 0, "btn")
        _draw_rounded_vertical_gradient(self, x1, y1, x2, y2,
            self._radius, t, b, bo, 1, "btn")
        yo = 1 if (self._pressed and self._enabled) else 0
        self.create_text(x1+(x2-x1)//2, y1+(y2-y1)//2+yo,
                         text=self._label, fill=tx, font=self._font, tags="btn")


class RoundedDropdown(tk.Canvas):
    def __init__(self, master: tk.Widget, *, variable: tk.StringVar,
                 values: list[str] | None = None, radius: int = 12,
                 height: int = 34, font: tuple = ("Avenir Next", 12),
                 max_popup_rows: int = 10,
                 placeholder: str = "Select…") -> None:
        super().__init__(master, height=height, highlightthickness=0, bd=0,
                         relief="flat", bg=master.cget("bg"),
                         cursor="hand2", takefocus=1)
        self.variable       = variable
        self.values         = list(values or [])
        self.radius         = radius
        self.font           = font
        self.max_popup_rows = max(3, max_popup_rows)
        self.placeholder    = placeholder
        self._enabled  = True
        self._hovered  = False
        self._pressed  = False
        self._popup: RoundedGradientCard | None = None
        self._listbox: tk.Listbox | None = None
        self._root_click_bindid: str | None = None
        self.variable.trace_add("write", lambda *_: self._redraw())
        self.bind("<Configure>",       lambda _e: self._redraw())
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>",           self._on_enter)
        self.bind("<Leave>",           self._on_leave)
        self.bind("<Escape>",          self._on_escape)
        self.bind("<Return>",          self._on_keyboard_toggle)
        self.bind("<space>",           self._on_keyboard_toggle)
        self.bind("<Down>",            self._on_keyboard_toggle)
        self.bind("<Destroy>",         self._on_destroy)
        self.after_idle(self._redraw)

    def set_values(self, values: list[str]) -> None:
        self.values = list(values)
        sel = self.variable.get().strip()
        if sel and sel not in self.values:
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

    def _on_destroy(self, _e: tk.Event) -> None: self.close_popup()
    def _on_press(self, e: tk.Event) -> None:
        if self._enabled and e.num == 1:
            self._pressed = True; self.focus_set(); self._redraw()
    def _on_release(self, e: tk.Event) -> None:
        if not self._enabled: return
        was = self._pressed; self._pressed = False; self._redraw()
        if not was: return
        if 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self._toggle_popup()
    def _on_enter(self, _e: tk.Event) -> None:
        if self._enabled: self._hovered = True; self._redraw()
    def _on_leave(self, _e: tk.Event) -> None:
        self._hovered = False; self._pressed = False; self._redraw()
    def _on_escape(self, _e: tk.Event) -> str:
        self.close_popup(); return "break"
    def _on_keyboard_toggle(self, _e: tk.Event) -> str:
        if self._enabled: self._toggle_popup()
        return "break"

    def _resolved_colors(self) -> tuple[str, str, str, str]:
        t  = _blend(FIELD_BG, "#ffffff", 0.06)
        b  = FIELD_BG
        bo = BORDER
        tx = TEXT_PRIMARY
        if not self._enabled:
            t = _blend(t, BG, 0.55); b = _blend(b, BG, 0.55)
            bo = _blend(bo, BG, 0.6); tx = _blend(tx, BG, 0.45)
        elif self._pressed:
            t = _blend(t, "#000000", 0.15); b = _blend(b, "#000000", 0.15)
        elif self._popup is not None:
            t = _blend(t, "#ffffff", 0.06); bo = _blend(BTN_BORDER, "#ffffff", 0.1)
        elif self._hovered:
            t = _blend(t, "#ffffff", 0.04); bo = _blend(bo, "#ffffff", 0.08)
        return t, b, bo, tx

    def _truncate(self, text: str, width_px: int) -> str:
        mc = max(4, width_px // 9)
        return text if len(text) <= mc else f"{text[:mc-1]}…"

    def _redraw(self) -> None:
        self.delete("dropdown")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 16 or h < 16: return
        t, b, bo, tx = self._resolved_colors()
        x1, y1, so = 1, 1, 2
        x2, y2 = w-2-so, h-2-so
        if x2 <= x1+2 or y2 <= y1+2: return
        sh = _blend(SHADOW_COLOR, BG, 0.35)
        _draw_rounded_vertical_gradient(self, x1+so, y1+so, x2+so, y2+so,
                                         self.radius, sh, sh, sh, 0, "dropdown")
        _draw_rounded_vertical_gradient(self, x1, y1, x2, y2,
                                         self.radius, t, b, bo, 1, "dropdown")
        cy = y1 + (y2-y1)//2
        ax = x2 - 14
        ac = tx if self._enabled else _blend(TEXT_SECONDARY, BG, 0.45)
        self.create_line(x2-26, y1+7, x2-26, y2-7,
                         fill=_blend(bo, BG, 0.25), width=1, tags="dropdown")
        self.create_polygon(ax-5, cy-2, ax+5, cy-2, ax, cy+4,
                            fill=ac, outline=ac, tags="dropdown")
        val  = self.variable.get().strip()
        disp = val if val else self.placeholder
        dc   = tx if val else _blend(TEXT_SECONDARY, BG, 0.12)
        self.create_text(x1+12, cy, text=self._truncate(disp, max(40,(x2-x1)-42)),
                         fill=dc, font=self.font, anchor="w", tags="dropdown")

    def _toggle_popup(self) -> None:
        if self._popup is not None: self.close_popup()
        else: self._open_popup()

    def _open_popup(self) -> None:
        if not self._enabled or not self.values or self._popup is not None: return
        host = self.winfo_toplevel()
        host.update_idletasks()
        w    = max(260, self.winfo_width())
        rows = min(self.max_popup_rows, max(1, len(self.values)))
        ph   = rows*28 + 16
        x    = self.winfo_rootx() - host.winfo_rootx()
        y    = self.winfo_rooty() - host.winfo_rooty() + self.winfo_height() + 4
        if y + ph > host.winfo_height() - 8:
            y = max(8, self.winfo_rooty() - host.winfo_rooty() - ph - 4)
        if x + w > host.winfo_width() - 8: x = max(8, host.winfo_width()-w-8)
        if x < 8: x = 8
        shell = RoundedGradientCard(host, radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.07), bottom_color=FIELD_BG,
            border_color=BORDER, content_bg=FIELD_BG, padding=6, shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35))
        shell.place(x=x, y=y, width=w, height=ph)
        shell.tk.call("raise", shell._w)
        inner = shell.content
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_rowconfigure(0, weight=1)
        lb = tk.Listbox(inner, bd=0, highlightthickness=0, relief="flat",
                        bg=FIELD_BG, fg=TEXT_PRIMARY,
                        selectbackground=BTN_TOP, selectforeground=TEXT_PRIMARY,
                        activestyle="none", font=("Avenir Next", 12),
                        exportselection=False)
        lb.grid(row=0, column=0, sticky="nsew")
        sb = tk.Scrollbar(inner, orient="vertical", command=lb.yview,
                          bd=0, highlightthickness=0, relief="flat",
                          background=_blend(FIELD_BG, "#ffffff", 0.12),
                          activebackground=BTN_TOP,
                          troughcolor=_blend(FIELD_BG, BG, 0.16))
        sb.grid(row=0, column=1, sticky="ns", padx=(6,0))
        lb.configure(yscrollcommand=sb.set)
        for v in self.values: lb.insert("end", v)
        sel = self.variable.get().strip()
        if sel in self.values:
            i = self.values.index(sel); lb.selection_set(i); lb.activate(i)
        lb.yview_moveto(0.0)
        lb.bind("<ButtonRelease-1>", self._on_listbox_select)
        lb.bind("<Double-Button-1>", self._on_listbox_select)
        lb.bind("<Return>",          self._on_listbox_select)
        lb.bind("<Escape>",          self._on_listbox_escape)
        lb.bind("<Motion>",          self._on_listbox_hover)
        self._popup = shell; self._listbox = lb
        self._root_click_bindid = host.bind("<Button-1>", self._on_root_click, add="+")
        lb.focus_set(); self._redraw()

    def _refresh_listbox(self) -> None:
        if self._listbox is None: return
        self._listbox.delete(0, "end")
        for v in self.values: self._listbox.insert("end", v)

    def _on_listbox_hover(self, e: tk.Event) -> None:
        if self._listbox is None: return
        i = self._listbox.nearest(e.y)
        self._listbox.selection_clear(0, "end")
        self._listbox.selection_set(i); self._listbox.activate(i)

    def _on_listbox_escape(self, _e: tk.Event) -> str:
        self.close_popup(); return "break"

    def _on_listbox_select(self, e: tk.Event) -> str:
        if self._listbox is None: self.close_popup(); return "break"
        if self._listbox.curselection():
            i = int(self._listbox.curselection()[0])
        elif hasattr(e, "y"):
            i = int(self._listbox.nearest(e.y))
        else:
            self.close_popup(); return "break"
        if 0 <= i < len(self.values): self.variable.set(self.values[i])
        self.close_popup(); return "break"

    def _widget_is_child_of(self, w: tk.Widget, parent: tk.Widget) -> bool:
        cur: tk.Widget | None = w
        while cur is not None:
            if cur == parent: return True
            cur = getattr(cur, "master", None)
        return False

    def _on_root_click(self, e: tk.Event) -> None:
        if self._popup is None: return
        if self._widget_is_child_of(e.widget, self): return
        if self._widget_is_child_of(e.widget, self._popup): return
        self.close_popup()

    def close_popup(self) -> None:
        if self._popup is not None:
            try: self._popup.destroy()
            except Exception: pass
        self._popup = None; self._listbox = None
        if self._root_click_bindid is not None:
            try: self.winfo_toplevel().unbind("<Button-1>", self._root_click_bindid)
            except Exception: pass
        self._root_click_bindid = None
        if self.winfo_exists(): self._redraw()


class RoundedSlider(tk.Canvas):
    def __init__(self, master: tk.Widget, *, variable: tk.IntVar,
                 min_value: int, max_value: int, height: int = 30) -> None:
        super().__init__(master, height=height, highlightthickness=0, bd=0,
                         relief="flat", bg=master.cget("bg"), cursor="hand2")
        self.variable  = variable
        self.min_value = min_value
        self.max_value = max_value
        self._enabled  = True
        self._dragging = False
        self.variable.trace_add("write", lambda *_: self._redraw())
        self.bind("<Configure>",      lambda _e: self._redraw())
        self.bind("<Button-1>",       self._on_down)
        self.bind("<B1-Motion>",      self._on_move)
        self.bind("<ButtonRelease-1>",self._on_up)
        self.after_idle(self._redraw)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled; self._dragging = False
        self.configure(cursor="hand2" if enabled else "arrow"); self._redraw()

    def _track_bounds(self) -> tuple[int,int,int,int]:
        w = max(30, self.winfo_width()); h = max(20, self.winfo_height())
        l, r = 12, max(13, w-12); th = 10; y1 = (h-th)//2; return l, r, y1, y1+th

    def _clamp(self, v: int) -> int:
        return max(self.min_value, min(self.max_value, int(v)))

    def _val_to_x(self, v: int) -> int:
        l, r, _, _ = self._track_bounds()
        return l + int((r-l) * (self._clamp(v)-self.min_value) / max(1, self.max_value-self.min_value))

    def _x_to_val(self, x: int) -> int:
        l, r, _, _ = self._track_bounds()
        ratio = (x-l) / max(1, r-l)
        return self._clamp(self.min_value + round(max(0.0,min(1.0,ratio))*(self.max_value-self.min_value)))

    def _set_from_x(self, x: int) -> None:
        if not self._enabled: return
        v = self._x_to_val(x)
        if v != self.variable.get(): self.variable.set(v)
        else: self._redraw()

    def _on_down(self, e: tk.Event) -> None:
        if self._enabled: self._dragging = True; self._set_from_x(e.x)
    def _on_move(self, e: tk.Event) -> None:
        if self._enabled and self._dragging: self._set_from_x(e.x)
    def _on_up(self, _e: tk.Event) -> None: self._dragging = False

    def _redraw(self) -> None:
        self.delete("slider")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 30 or h < 14: return
        v = self._clamp(self.variable.get())
        l, r, y1, y2 = self._track_bounds(); rad = (y2-y1)//2
        sh = _blend(SHADOW_COLOR, BG, 0.35)
        _draw_rounded_vertical_gradient(self, l+1, y1+2, r+1, y2+2, rad,
                                         sh, sh, sh, 0, "slider")
        _draw_rounded_vertical_gradient(self, l, y1, r, y2, rad,
            _blend(FIELD_BG, "#ffffff", 0.04), FIELD_BG,
            _blend(BORDER, BG, 0.25), 1, "slider")
        vx = self._val_to_x(v)
        _draw_rounded_vertical_gradient(self, l, y1, max(l+rad, vx), y2, rad,
                                         BTN_TOP, BTN_BOTTOM, BTN_BORDER, 0, "slider")
        tr = 8; cx = vx; cy = (y1+y2)//2
        tf = TEXT_PRIMARY if self._enabled else _blend(TEXT_PRIMARY, BG, 0.4)
        tb = BTN_BORDER  if self._enabled else _blend(BTN_BORDER, BG, 0.5)
        self.create_oval(cx-tr, cy-tr, cx+tr, cy+tr, fill=tf, outline=tb, width=1, tags="slider")


# ── main app ──────────────────────────────────────────────────────────────────

class DesktopApp(tk.Tk):
    def __init__(self, tool_paths: dict[str, str]) -> None:
        super().__init__()
        self.say_cmd      = tool_paths["say"]
        self.afconvert_cmd = tool_paths["afconvert"]
        self.afplay_cmd   = tool_paths["afplay"]

        self.title("Vocal Canvas")
        self.geometry("980x720")
        self.minsize(860, 630)
        self.configure(bg=BG)

        self.preview_path   = Path(tempfile.gettempdir()) / "vocal_canvas_preview.wav"
        self.player_process: subprocess.Popen | None = None

        # Studio tab
        self.voice_var      = tk.StringVar()
        self.rate_var       = tk.IntVar(value=170)
        self.char_count_var = tk.StringVar(value="0 characters")

        # VC tab
        self.vc_voice_var  = tk.StringVar()
        self.vc_rate_var   = tk.IntVar(value=200)
        self.vc_mic_var    = tk.StringVar(value="Default")
        self.vc_model_var  = tk.StringVar(value="tiny")
        self.vc_q: queue.Queue = queue.Queue()
        self.vc_model: WhisperModel | None = None
        self.vc_stream: sd.InputStream | None = None
        self.vc_listening  = False
        self.vc_say_procs: list[subprocess.Popen] = []
        self.vc_tts_until  = 0.0
        self.vc_bh_name: str | None = None

        self.tab_buttons: dict[str, RoundedGradientButton] = {}
        self.pages: dict[str, tk.Frame] = {}

        self._build_ui()
        self._load_voices()
        self._update_char_count()
        self._set_tab("demo")

        threading.Thread(target=self._vc_detect_bh, daemon=True).start()
        self._vc_load_model("tiny")
        self._poll_vc_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── shell ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=24)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(3, weight=1)

        tk.Label(outer, text="Vocal Canvas", bg=BG, fg=TEXT_PRIMARY,
                 font=("Avenir Next", 34, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(outer,
                 text="Desktop text-to-speech studio with local voices, preview, and export.",
                 bg=BG, fg=TEXT_SECONDARY,
                 font=("Avenir Next", 13)).grid(row=1, column=0, sticky="w", pady=(4,14))

        tab_row = tk.Frame(outer, bg=BG)
        tab_row.grid(row=2, column=0, sticky="ew", pady=(0,10))
        tabs = [("home","Home"), ("demo","Studio"), ("qa","Q&A"), ("vc","Voice Canvas")]
        for i, _ in enumerate(tabs):
            tab_row.grid_columnconfigure(i, weight=1)
        for index, (key, label) in enumerate(tabs):
            btn = RoundedGradientButton(
                tab_row, text=label,
                command=lambda k=key: self._set_tab(k),
                top_color=TAB_INACTIVE_TOP, bottom_color=TAB_INACTIVE_BOTTOM,
                border_color=TAB_INACTIVE_BORDER, text_color=TEXT_SECONDARY,
                radius=12, height=36, font=("Avenir Next", 10, "bold"),
                shadow_offset=1)
            btn.grid(row=0, column=index, sticky="ew",
                     padx=(0 if index == 0 else 6, 0))
            self.tab_buttons[key] = btn

        page_card = RoundedGradientCard(
            outer, radius=28, top_color=CARD_TOP, bottom_color=CARD_BOTTOM,
            border_color=BORDER, content_bg=CARD_INNER, padding=18,
            shadow_offset=4, shadow_color=_blend(SHADOW_COLOR, BG, 0.35))
        page_card.grid(row=3, column=0, sticky="nsew")
        host = page_card.content
        host.grid_columnconfigure(0, weight=1)
        host.grid_rowconfigure(0, weight=1)

        self.pages["home"] = self._build_placeholder_page(host,
            heading="Vocal Canvas", version="v0.1.1 (Beta)",
            copy=("The Home tab is still being expanded. More information and "
                  "quick access features will be added in future updates."))
        self.pages["demo"] = self._build_demo_page(host)
        self.pages["qa"]   = self._build_placeholder_page(host,
            heading="Vocal Canvas", version="v0.1.1 (Beta)",
            copy=("The Q&A section is currently being expanded. Detailed answers "
                  "and documentation will be available soon."))
        self.pages["vc"]   = self._build_vc_page(host)

        for frame in self.pages.values():
            frame.grid(row=0, column=0, sticky="nsew")

    def _build_placeholder_page(self, parent: tk.Widget, *, heading: str,
                                  version: str, copy: str) -> tk.Frame:
        frame = tk.Frame(parent, bg=CARD_INNER)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        holder = tk.Frame(frame, bg=CARD_INNER)
        holder.grid(row=0, column=0, sticky="nsew")
        tk.Label(holder, text=heading, bg=CARD_INNER, fg=TEXT_PRIMARY,
                 font=("Avenir Next", 24, "bold"), anchor="w").pack(anchor="w")
        tk.Label(holder, text=version, bg=CARD_INNER, fg=TEXT_PRIMARY,
                 font=("Avenir Next", 14, "bold"), anchor="w").pack(anchor="w", pady=(6,0))
        if copy:
            tk.Label(holder, text=copy, bg=CARD_INNER, fg=TEXT_SECONDARY,
                     font=("Avenir Next", 12), anchor="w", justify="left",
                     wraplength=760).pack(anchor="w", pady=(10,0))
        return frame

    def _build_demo_page(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=CARD_INNER)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        tk.Label(frame, text="Script", bg=CARD_INNER, fg=TEXT_PRIMARY,
                 font=("Avenir Next", 12, "bold")).grid(row=0, column=0,
                                                         sticky="w", pady=(2,6))
        text_shell = RoundedGradientCard(
            frame, radius=16,
            top_color=_blend(FIELD_BG, "#ffffff", 0.07), bottom_color=FIELD_BG,
            border_color=BORDER, content_bg=FIELD_BG, padding=1, shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35))
        text_shell.grid(row=1, column=0, sticky="nsew")
        text_shell.content.grid_columnconfigure(0, weight=1)
        text_shell.content.grid_rowconfigure(0, weight=1)

        self.text_box = tk.Text(
            text_shell.content, wrap="word", height=11, bd=0,
            highlightthickness=0, font=("Avenir Next", 13),
            padx=12, pady=10, bg=FIELD_BG, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY, relief="flat")
        self.text_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.text_box.insert("1.0", DEFAULT_TEXT)
        self.text_box.bind("<KeyRelease>", lambda _e: self._update_char_count())

        meta = tk.Frame(frame, bg=CARD_INNER)
        meta.grid(row=2, column=0, sticky="ew", pady=(8,0))
        meta.grid_columnconfigure(0, weight=1)
        self.char_count_label = tk.Label(meta, textvariable=self.char_count_var,
                                          bg=CARD_INNER, fg=TEXT_SECONDARY,
                                          font=("Avenir Next", 10, "bold"), anchor="e")
        self.char_count_label.grid(row=0, column=0, sticky="e")

        ctrl = tk.Frame(frame, bg=CARD_INNER)
        ctrl.grid(row=3, column=0, sticky="ew", pady=(10,0))
        ctrl.grid_columnconfigure(0, weight=1)
        ctrl.grid_columnconfigure(1, weight=1)

        for col, lbl in enumerate(("Voice", "Speed")):
            tk.Label(ctrl, text=lbl, bg=CARD_INNER, fg=TEXT_PRIMARY,
                     font=("Avenir Next", 11, "bold")).grid(row=0, column=col, sticky="w")

        vs = RoundedGradientCard(ctrl, radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.06), bottom_color=FIELD_BG,
            border_color=BORDER, content_bg=FIELD_BG, padding=2, shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35))
        vs.grid(row=1, column=0, sticky="ew", padx=(0,10), pady=(4,0))
        vs.configure(height=44); vs.content.grid_columnconfigure(0, weight=1)
        self.voice_combo = RoundedDropdown(vs.content, variable=self.voice_var,
            values=[], radius=10, height=34, font=("Avenir Next", 12),
            max_popup_rows=11, placeholder="Select voice")
        self.voice_combo.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        ss = RoundedGradientCard(ctrl, radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.06), bottom_color=FIELD_BG,
            border_color=BORDER, content_bg=FIELD_BG, padding=4, shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35))
        ss.grid(row=1, column=1, sticky="ew", pady=(4,0))
        ss.configure(height=44); ss.content.grid_columnconfigure(0, weight=1)
        sp = tk.Frame(ss.content, bg=FIELD_BG)
        sp.grid(row=0, column=0, sticky="ew"); sp.grid_columnconfigure(0, weight=1)
        self.rate_slider = RoundedSlider(sp, variable=self.rate_var,
                                          min_value=MIN_RATE, max_value=MAX_RATE, height=30)
        self.rate_slider.grid(row=0, column=0, sticky="ew")
        self.rate_label = tk.Label(sp, text=str(self.rate_var.get()),
                                    bg=FIELD_BG, fg=TEXT_SECONDARY,
                                    font=("Avenir Next", 10, "bold"))
        self.rate_label.grid(row=0, column=1, sticky="w", padx=(8,0))
        self.rate_var.trace_add("write",
            lambda *_: self.rate_label.config(text=str(self.rate_var.get())))

        self.generate_btn = RoundedGradientButton(frame, text="Generate Audio",
            command=self.preview_audio, top_color=BTN_TOP, bottom_color=BTN_BOTTOM,
            border_color=BTN_BORDER, text_color=TEXT_PRIMARY, radius=14, height=46,
            font=("Avenir Next", 12, "bold"), shadow_offset=2)
        self.generate_btn.grid(row=4, column=0, sticky="ew", pady=(12,0))

        ar = tk.Frame(frame, bg=CARD_INNER)
        ar.grid(row=5, column=0, sticky="ew", pady=(8,0))
        ar.grid_columnconfigure(0, weight=1); ar.grid_columnconfigure(1, weight=1)
        self.export_btn = RoundedGradientButton(ar, text="Export WAV",
            command=self.export_audio, top_color=BTN_TOP, bottom_color=BTN_BOTTOM,
            border_color=BTN_BORDER, text_color=TEXT_PRIMARY, radius=12, height=40,
            font=("Avenir Next", 11, "bold"), shadow_offset=2)
        self.export_btn.grid(row=0, column=0, sticky="ew", padx=(0,8))
        self.clear_btn = RoundedGradientButton(ar, text="Clear",
            command=self.clear_text, top_color=BTN_TOP, bottom_color=BTN_BOTTOM,
            border_color=BTN_BORDER, text_color=TEXT_PRIMARY, radius=12, height=40,
            font=("Avenir Next", 11, "bold"), shadow_offset=2)
        self.clear_btn.grid(row=0, column=1, sticky="ew")
        self.status = tk.Label(frame, text="Ready.", bg=CARD_INNER, fg=TEXT_SECONDARY,
                                font=("Avenir Next", 10, "bold"), anchor="w")
        self.status.grid(row=6, column=0, sticky="ew", pady=(10,2))
        return frame

    # ── VC page ───────────────────────────────────────────────────────────────

    def _build_vc_page(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=CARD_INNER)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(4, weight=1)   # transcript expands

        # header
        hdr = tk.Frame(frame, bg=CARD_INNER)
        hdr.grid(row=0, column=0, sticky="ew", pady=(2,10))
        tk.Label(hdr, text="Voice Canvas", bg=CARD_INNER, fg=TEXT_PRIMARY,
                 font=("Avenir Next", 20, "bold")).pack(side="left")
        tk.Label(hdr, text="  on-device · real-time", bg=CARD_INNER, fg=TEXT_SECONDARY,
                 font=("Avenir Next", 12)).pack(side="left", pady=(4,0))

        # ── row 1: Voice + Rate ──────────────────────────────────────────────
        row1 = tk.Frame(frame, bg=CARD_INNER)
        row1.grid(row=1, column=0, sticky="ew", pady=(0,6))
        row1.grid_columnconfigure(0, weight=2)
        row1.grid_columnconfigure(1, weight=1)

        tk.Label(row1, text="Voice", bg=CARD_INNER, fg=TEXT_PRIMARY,
                 font=("Avenir Next", 11, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(row1, text="Rate", bg=CARD_INNER, fg=TEXT_PRIMARY,
                 font=("Avenir Next", 11, "bold")).grid(row=0, column=1, sticky="w", padx=(8,0))

        vc_vs = RoundedGradientCard(row1, radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.06), bottom_color=FIELD_BG,
            border_color=BORDER, content_bg=FIELD_BG, padding=2, shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35))
        vc_vs.grid(row=1, column=0, sticky="ew", padx=(0,8), pady=(4,0))
        vc_vs.configure(height=44); vc_vs.content.grid_columnconfigure(0, weight=1)
        self.vc_voice_combo = RoundedDropdown(vc_vs.content, variable=self.vc_voice_var,
            values=[], radius=10, height=34, font=("Avenir Next", 12),
            max_popup_rows=11, placeholder="Select voice")
        self.vc_voice_combo.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        vc_ss = RoundedGradientCard(row1, radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.06), bottom_color=FIELD_BG,
            border_color=BORDER, content_bg=FIELD_BG, padding=4, shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35))
        vc_ss.grid(row=1, column=1, sticky="ew", pady=(4,0))
        vc_ss.configure(height=44); vc_ss.content.grid_columnconfigure(0, weight=1)
        vc_sp = tk.Frame(vc_ss.content, bg=FIELD_BG)
        vc_sp.grid(row=0, column=0, sticky="ew"); vc_sp.grid_columnconfigure(0, weight=1)
        self.vc_rate_slider = RoundedSlider(vc_sp, variable=self.vc_rate_var,
                                             min_value=80, max_value=400, height=30)
        self.vc_rate_slider.grid(row=0, column=0, sticky="ew")
        self.vc_rate_label = tk.Label(vc_sp, text=str(self.vc_rate_var.get()),
                                       bg=FIELD_BG, fg=TEXT_SECONDARY,
                                       font=("Avenir Next", 10, "bold"))
        self.vc_rate_label.grid(row=0, column=1, sticky="w", padx=(8,0))
        self.vc_rate_var.trace_add("write",
            lambda *_: self.vc_rate_label.config(text=str(self.vc_rate_var.get())))

        # ── row 2: Mic + Model ───────────────────────────────────────────────
        row2 = tk.Frame(frame, bg=CARD_INNER)
        row2.grid(row=2, column=0, sticky="ew", pady=(0,6))
        row2.grid_columnconfigure(0, weight=2)
        row2.grid_columnconfigure(1, weight=1)

        tk.Label(row2, text="Mic", bg=CARD_INNER, fg=TEXT_PRIMARY,
                 font=("Avenir Next", 11, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(row2, text="Model", bg=CARD_INNER, fg=TEXT_PRIMARY,
                 font=("Avenir Next", 11, "bold")).grid(row=0, column=1, sticky="w", padx=(8,0))

        mics = ["Default"] + [d["name"] for d in sd.query_devices()
                               if d["max_input_channels"] > 0]
        vc_ms = RoundedGradientCard(row2, radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.06), bottom_color=FIELD_BG,
            border_color=BORDER, content_bg=FIELD_BG, padding=2, shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35))
        vc_ms.grid(row=1, column=0, sticky="ew", padx=(0,8), pady=(4,0))
        vc_ms.configure(height=44); vc_ms.content.grid_columnconfigure(0, weight=1)
        self.vc_mic_combo = RoundedDropdown(vc_ms.content, variable=self.vc_mic_var,
            values=mics, radius=10, height=34, font=("Avenir Next", 12),
            placeholder="Select mic")
        self.vc_mic_combo.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        vc_mo = RoundedGradientCard(row2, radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.06), bottom_color=FIELD_BG,
            border_color=BORDER, content_bg=FIELD_BG, padding=2, shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35))
        vc_mo.grid(row=1, column=1, sticky="ew", pady=(4,0))
        vc_mo.configure(height=44); vc_mo.content.grid_columnconfigure(0, weight=1)
        self.vc_model_combo = RoundedDropdown(vc_mo.content, variable=self.vc_model_var,
            values=VC_MODEL_SIZES, radius=10, height=34, font=("Avenir Next", 12),
            placeholder="Model")
        self.vc_model_combo.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.vc_model_var.trace_add("write",
            lambda *_: self.after_idle(self._vc_on_model_change))

        # ── row 3: BlackHole status + volume bar ─────────────────────────────
        row3 = tk.Frame(frame, bg=CARD_INNER)
        row3.grid(row=3, column=0, sticky="ew", pady=(0,6))
        row3.grid_columnconfigure(1, weight=1)

        bh_frame = tk.Frame(row3, bg=CARD_INNER)
        bh_frame.grid(row=0, column=0, sticky="w")
        self.vc_bh_dot = tk.Label(bh_frame, text="●", bg=CARD_INNER,
                                   fg=TEXT_SECONDARY, font=("Avenir Next", 12))
        self.vc_bh_dot.pack(side="left")
        self.vc_bh_lbl = tk.Label(bh_frame, text="Virtual mic: detecting…",
                                   bg=CARD_INNER, fg=TEXT_SECONDARY,
                                   font=("Avenir Next", 11))
        self.vc_bh_lbl.pack(side="left", padx=(4,0))

        self.vc_vol_cv = tk.Canvas(row3, height=6, bg=_blend(FIELD_BG, BG, 0.5),
                                    highlightthickness=0)
        self.vc_vol_cv.grid(row=0, column=1, sticky="ew", padx=(16,0))
        self.vc_vol_bar = self.vc_vol_cv.create_rectangle(0, 0, 0, 6,
                                                            fill=BTN_TOP, width=0)

        # ── row 4: Transcript ─────────────────────────────────────────────────
        tx_card = RoundedGradientCard(frame, radius=16,
            top_color=_blend(FIELD_BG, "#ffffff", 0.07), bottom_color=FIELD_BG,
            border_color=BORDER, content_bg=FIELD_BG, padding=1, shadow_offset=2,
            shadow_color=_blend(SHADOW_COLOR, BG, 0.35))
        tx_card.grid(row=4, column=0, sticky="nsew")
        tx_card.content.grid_columnconfigure(0, weight=1)
        tx_card.content.grid_rowconfigure(0, weight=1)

        self.vc_text = tk.Text(
            tx_card.content, wrap="word", height=8, bd=0, highlightthickness=0,
            font=("Avenir Next", 13), padx=12, pady=10,
            bg=FIELD_BG, fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
            relief="flat", state="disabled")
        vc_sb = tk.Scrollbar(tx_card.content, orient="vertical",
                              command=self.vc_text.yview, bd=0,
                              highlightthickness=0, relief="flat",
                              background=_blend(FIELD_BG, "#ffffff", 0.12),
                              activebackground=BTN_TOP,
                              troughcolor=_blend(FIELD_BG, BG, 0.16))
        self.vc_text.configure(yscrollcommand=vc_sb.set)
        self.vc_text.grid(row=0, column=0, sticky="nsew", padx=(8,0), pady=8)
        vc_sb.grid(row=0, column=1, sticky="ns", pady=8, padx=(4,6))
        self.vc_text.tag_configure("fresh", foreground=WARNING)

        # ── row 5: action bar ─────────────────────────────────────────────────
        act = tk.Frame(frame, bg=CARD_INNER)
        act.grid(row=5, column=0, sticky="ew", pady=(8,2))
        act.grid_columnconfigure(0, weight=1)

        sf2 = tk.Frame(act, bg=CARD_INNER)
        sf2.grid(row=0, column=0, sticky="w")
        self.vc_dot = tk.Label(sf2, text="●", bg=CARD_INNER, fg=TEXT_SECONDARY,
                                font=("Avenir Next", 15))
        self.vc_dot.pack(side="left", padx=(0,6))
        self.vc_status_lbl = tk.Label(sf2, text="Loading model…",
                                       bg=CARD_INNER, fg=TEXT_SECONDARY,
                                       font=("Avenir Next", 10, "bold"))
        self.vc_status_lbl.pack(side="left")

        self.vc_clear_btn = RoundedGradientButton(act, text="Clear",
            command=self._vc_clear, top_color=BTN_TOP, bottom_color=BTN_BOTTOM,
            border_color=BTN_BORDER, text_color=TEXT_PRIMARY, radius=12, height=40,
            font=("Avenir Next", 11, "bold"), shadow_offset=2)
        self.vc_clear_btn.grid(row=0, column=1, padx=(0,8))

        self.vc_start_btn = RoundedGradientButton(act, text="▶  Start",
            command=self._vc_toggle,
            top_color=_blend(BTN_TOP, BG, 0.55),
            bottom_color=_blend(BTN_BOTTOM, BG, 0.55),
            border_color=_blend(BTN_BORDER, BG, 0.5),
            text_color=_blend(TEXT_PRIMARY, BG, 0.45),
            radius=12, height=40, font=("Avenir Next", 11, "bold"), shadow_offset=2)
        self.vc_start_btn.set_enabled(False)
        self.vc_start_btn.grid(row=0, column=2)

        return frame

    # ── tab switching ─────────────────────────────────────────────────────────

    def _set_tab(self, name: str) -> None:
        if name not in self.pages: return
        self.pages[name].tkraise()
        for key, btn in self.tab_buttons.items():
            if key == name:
                btn.set_palette(TAB_ACTIVE_TOP, TAB_ACTIVE_BOTTOM,
                                TAB_ACTIVE_BORDER, TEXT_PRIMARY)
            else:
                btn.set_palette(TAB_INACTIVE_TOP, TAB_INACTIVE_BOTTOM,
                                TAB_INACTIVE_BORDER, TEXT_SECONDARY)

    # ── voices ────────────────────────────────────────────────────────────────

    def _load_voices(self) -> None:
        try:
            voices = parse_voices(self.say_cmd)
        except Exception as exc:
            log_exception("load voices", exc)
            messagebox.showerror("Voices", f"Unable to load voices.\n\nLog: {LOG_FILE}")
            voices = []
        self.voice_combo.set_values(voices)
        self.vc_voice_combo.set_values(voices)
        default = next((v for v in ("Samantha", "Daniel", "Alex") if v in voices),
                       voices[0] if voices else "")
        self.voice_var.set(default)
        self.vc_voice_var.set(default)
        if not voices:
            self._set_status("No voices found.", "error")

    # ── Studio helpers ────────────────────────────────────────────────────────

    def _set_status(self, msg: str, kind: str = "idle") -> None:
        color = {
            "success": SUCCESS, "error": ERROR, "loading": WARNING
        }.get(kind, TEXT_SECONDARY)
        self.status.config(text=msg, fg=color)

    def _set_busy(self, busy: bool) -> None:
        e = not busy
        self.generate_btn.set_enabled(e); self.export_btn.set_enabled(e)
        self.clear_btn.set_enabled(e);    self.rate_slider.set_enabled(e)
        self.voice_combo.set_enabled(e)

    def _update_char_count(self) -> None:
        n = len(self.text_box.get("1.0", "end").strip())
        self.char_count_var.set(f"{n} character{'s' if n != 1 else ''}")

    def _collect_inputs(self) -> tuple[str, str, int] | None:
        text  = self.text_box.get("1.0", "end").strip()
        voice = self.voice_var.get().strip()
        rate  = int(self.rate_var.get())
        if not text:  messagebox.showerror("Missing text", "Please enter text."); return None
        if not voice: messagebox.showerror("Missing voice", "Please choose a voice."); return None
        if not MIN_RATE <= rate <= MAX_RATE:
            messagebox.showerror("Invalid speed", f"Speed must be {MIN_RATE}–{MAX_RATE}.")
            return None
        return text, voice, rate

    def _play_file(self, path: Path) -> None:
        if self.player_process and self.player_process.poll() is None:
            self.player_process.terminate()
        self.player_process = subprocess.Popen([self.afplay_cmd, str(path)])

    def clear_text(self) -> None:
        self.text_box.delete("1.0", "end"); self._update_char_count()
        self._set_status("Ready.")

    def preview_audio(self) -> None:
        payload = self._collect_inputs()
        if not payload: return
        text, voice, rate = payload
        self._set_busy(True); self._set_status("Generating preview...", "loading")
        self.update_idletasks()
        try:
            render_wav(text=text, voice=voice, rate=rate,
                       output_path=self.preview_path,
                       say_cmd=self.say_cmd, afconvert_cmd=self.afconvert_cmd)
            self._play_file(self.preview_path)
            self._set_status(f"Preview playing with {voice} at {rate}.", "success")
        except Exception as exc:
            log_exception("preview", exc)
            messagebox.showerror("Preview failed", f"Something went wrong.\n\nLog: {LOG_FILE}")
            self._set_status("Preview failed.", "error")
        finally:
            self._set_busy(False)

    def export_audio(self) -> None:
        payload = self._collect_inputs()
        if not payload: return
        text, voice, rate = payload
        path = filedialog.asksaveasfilename(title="Save speech as…",
            defaultextension=".wav", initialfile="vocal_canvas.wav",
            filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")])
        if not path: return
        output = Path(path)
        self._set_busy(True); self._set_status("Exporting...", "loading")
        self.update_idletasks()
        try:
            render_wav(text=text, voice=voice, rate=rate, output_path=output,
                       say_cmd=self.say_cmd, afconvert_cmd=self.afconvert_cmd)
            self._set_status(f"Saved to {output.name}.", "success")
            messagebox.showinfo("Saved", f"Audio exported to:\n{output}")
        except Exception as exc:
            log_exception("export", exc)
            messagebox.showerror("Export failed", f"Something went wrong.\n\nLog: {LOG_FILE}")
            self._set_status("Export failed.", "error")
        finally:
            self._set_busy(False)

    # ── VC: BlackHole detection ───────────────────────────────────────────────

    def _vc_detect_bh(self) -> None:
        out = subprocess.run([self.say_cmd, "-a", "?"],
                              capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "BlackHole" in line:
                self.vc_bh_name = line.split(None, 1)[-1].strip()
                self.vc_q.put(("bh", f"Virtual mic: {self.vc_bh_name}  ✓", BTN_BORDER))
                return
        self.vc_q.put(("bh", "Virtual mic: BlackHole not found — install via brew", ERROR))

    # ── VC: model loading ─────────────────────────────────────────────────────

    def _vc_load_model(self, size: str) -> None:
        self.vc_model = None
        if hasattr(self, "vc_start_btn"):
            self.vc_start_btn.set_enabled(False)
            self.vc_start_btn.set_palette(
                _blend(BTN_TOP, BG, 0.55), _blend(BTN_BOTTOM, BG, 0.55),
                _blend(BTN_BORDER, BG, 0.5), _blend(TEXT_PRIMARY, BG, 0.45))
        self.vc_q.put(("status", f"Loading {size} model…", WARNING))

        def _load() -> None:
            try:
                m = WhisperModel(size, device="cpu", compute_type="int8")
                self.vc_model = m
                self.vc_q.put(("status", f"{size} model ready", SUCCESS))
                self.vc_q.put(("enable_btn",))
            except Exception as exc:
                self.vc_q.put(("status", f"Model error: {exc}", ERROR))

        threading.Thread(target=_load, daemon=True).start()

    def _vc_on_model_change(self) -> None:
        size = self.vc_model_var.get()
        if not size: return
        if self.vc_listening:
            self._vc_stop()
        self._vc_load_model(size)

    # ── VC: listen toggle ─────────────────────────────────────────────────────

    def _vc_toggle(self) -> None:
        if self.vc_listening: self._vc_stop()
        else: self._vc_start()

    def _vc_start(self) -> None:
        self.vc_listening = True
        self.vc_start_btn.set_text("■  Stop")
        self.vc_start_btn.set_palette(ERROR, _blend(ERROR, "#000", 0.2),
                                       _blend(ERROR, "#fff", 0.15), TEXT_PRIMARY)
        self.vc_q.put(("status", "Listening", BORDER))
        self.vc_q.put(("dot", BORDER))

        mic = self.vc_mic_var.get()
        device: str | None = None if mic == "Default" else mic
        self.vc_stream = sd.InputStream(
            samplerate=VC_RATE, channels=1, dtype="float32",
            blocksize=VC_CHUNK_N, device=device,
            callback=self._vc_audio_cb)
        self.vc_stream.start()
        threading.Thread(target=self._vc_vad_loop, daemon=True).start()

    def _vc_stop(self) -> None:
        self.vc_listening = False
        self.vc_start_btn.set_text("▶  Start")
        self.vc_start_btn.set_palette(BTN_TOP, BTN_BOTTOM, BTN_BORDER, TEXT_PRIMARY)
        self.vc_q.put(("status", "Ready", TEXT_SECONDARY))
        self.vc_q.put(("dot", TEXT_SECONDARY))
        if self.vc_stream:
            self.vc_stream.stop(); self.vc_stream.close(); self.vc_stream = None

    # ── VC: audio pipeline ────────────────────────────────────────────────────

    def _vc_audio_cb(self, indata: np.ndarray, frames: int,
                     time_info, status) -> None:
        try:
            self._vc_audio_q.put_nowait(indata[:, 0].copy())
        except Exception:
            pass

    def _vc_vad_loop(self) -> None:
        self._vc_audio_q: queue.Queue = queue.Queue(maxsize=200)
        pre_buf: list[np.ndarray] = []
        spk_buf: list[np.ndarray] = []
        in_speech = False
        sil_count = 0

        while self.vc_listening:
            try:
                chunk = self._vc_audio_q.get(timeout=0.3)
            except queue.Empty:
                continue

            rms = float(np.sqrt(np.mean(chunk ** 2)))
            self.vc_q.put(("vol", min(rms / 0.08, 1.0)))

            if time.time() < self.vc_tts_until:
                in_speech = False; spk_buf = []; pre_buf = []; sil_count = 0
                continue

            if not in_speech:
                pre_buf.append(chunk)
                if len(pre_buf) > VC_PRE_ROLL: pre_buf.pop(0)
                if rms >= VC_VOICE_ON_RMS:
                    in_speech = True; sil_count = 0
                    spk_buf = list(pre_buf)
                    self.vc_q.put(("dot", WARNING))
            else:
                spk_buf.append(chunk)
                if rms < VC_VOICE_OFF_RMS:
                    sil_count += 1
                    if sil_count >= VC_SILENCE_CHUNKS:
                        if len(spk_buf) >= VC_MIN_CHUNKS:
                            audio = np.concatenate(spk_buf).astype(np.float32)
                            threading.Thread(target=self._vc_transcribe,
                                             args=(audio,), daemon=True).start()
                        in_speech = False; spk_buf = []; pre_buf = []; sil_count = 0
                        self.vc_q.put(("dot", BORDER))
                else:
                    sil_count = 0

    def _vc_transcribe(self, audio: np.ndarray) -> None:
        if self.vc_model is None: return
        self.vc_q.put(("dot", SUCCESS))
        try:
            segs, _ = self.vc_model.transcribe(
                audio, beam_size=1, best_of=1, temperature=0.0,
                vad_filter=False, condition_on_previous_text=False,
                without_timestamps=True)
            text = " ".join(s.text for s in segs).strip()
            text = re.sub(r"\s+", " ", text)
            if text and not re.fullmatch(r"[\s.。，,!?！？…]+", text):
                self.vc_q.put(("text", text))
                threading.Thread(target=self._vc_speak,
                                 args=(text,), daemon=True).start()
        except Exception as exc:
            self.vc_q.put(("status", str(exc), ERROR))
        finally:
            if self.vc_listening:
                self.vc_q.put(("dot", BORDER))

    def _vc_speak(self, text: str) -> None:
        for p in self.vc_say_procs:
            if p.poll() is None: p.terminate()
        self.vc_say_procs.clear()

        voice = self.vc_voice_var.get()
        rate  = self.vc_rate_var.get()
        base  = [self.say_cmd, "-v", voice, "-r", str(rate), text]

        p_spk = subprocess.Popen(base)
        self.vc_say_procs.append(p_spk)

        p_bh: subprocess.Popen | None = None
        if self.vc_bh_name:
            p_bh = subprocess.Popen(
                [self.say_cmd, "-v", voice, "-r", str(rate),
                 "-a", self.vc_bh_name, text])
            self.vc_say_procs.append(p_bh)

        def _wait() -> None:
            p_spk.wait()
            if p_bh: p_bh.wait()
            self.vc_tts_until = time.time() + 0.5

        threading.Thread(target=_wait, daemon=True).start()

    # ── VC: UI helpers ────────────────────────────────────────────────────────

    def _vc_set_status(self, text: str, color: str) -> None:
        self.vc_status_lbl.config(text=text, fg=color)
        self.vc_dot.config(fg=color)

    def _vc_append(self, text: str) -> None:
        self.vc_text.config(state="normal")
        if self.vc_text.index("end-1c") != "1.0":
            self.vc_text.insert("end", "\n")
        start = self.vc_text.index("end")
        self.vc_text.insert("end", text, "fresh")
        self.vc_text.see("end")
        self.vc_text.config(state="disabled")
        self.after(700, lambda: (
            self.vc_text.tag_remove("fresh", start, "end")
            if self.vc_text.winfo_exists() else None))

    def _vc_clear(self) -> None:
        self.vc_text.config(state="normal")
        self.vc_text.delete("1.0", "end")
        self.vc_text.config(state="disabled")

    def _poll_vc_ui(self) -> None:
        W = self.vc_vol_cv.winfo_width() or 400
        try:
            while True:
                msg = self.vc_q.get_nowait()
                k = msg[0]
                if k == "text":
                    self._vc_append(msg[1])
                elif k == "status":
                    self._vc_set_status(msg[1], msg[2])
                elif k == "dot":
                    self.vc_dot.config(fg=msg[1])
                elif k == "vol":
                    v = msg[1]
                    self.vc_vol_cv.coords(self.vc_vol_bar, 0, 0, int(W*v), 6)
                    self.vc_vol_cv.itemconfig(
                        self.vc_vol_bar, fill=ERROR if v > 0.9 else BTN_TOP)
                elif k == "bh":
                    self.vc_bh_lbl.config(text=msg[1], fg=msg[2])
                    self.vc_bh_dot.config(fg=msg[2])
                elif k == "enable_btn":
                    self.vc_start_btn.set_enabled(True)
                    self.vc_start_btn.set_palette(BTN_TOP, BTN_BOTTOM,
                                                   BTN_BORDER, TEXT_PRIMARY)
        except queue.Empty:
            pass
        self.after(30, self._poll_vc_ui)

    # ── close ─────────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self.player_process and self.player_process.poll() is None:
            self.player_process.terminate()
        if self.vc_listening:
            self._vc_stop()
        for p in self.vc_say_procs:
            if p.poll() is None: p.terminate()
        self.voice_combo.close_popup()
        self.vc_voice_combo.close_popup()
        self.vc_mic_combo.close_popup()
        self.vc_model_combo.close_popup()
        self.destroy()


# ── entry ──────────────────────────────────────────────────────────────────────

def main() -> int:
    log_line("=== Vocal Canvas launch ===")
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
        log_exception("Unhandled exception", exc)
        show_startup_error("Vocal Canvas", f"The app crashed.\n\nLog: {LOG_FILE}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
