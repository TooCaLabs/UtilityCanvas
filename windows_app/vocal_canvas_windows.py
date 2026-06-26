#!/usr/bin/env python3
from __future__ import annotations

import math
import tempfile
import tkinter as tk
import winsound
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import pyttsx3
except Exception as exc:  # pragma: no cover - depends on runtime environment
    pyttsx3 = None
    PYTTSX3_IMPORT_ERROR = str(exc)
else:
    PYTTSX3_IMPORT_ERROR = ""

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

DEFAULT_TEXT = (
    "Download Vocal-Canvas today, this is made to help content creators use "
    "TextToSpeech easily in their videos!"
)
MIN_RATE = 80
MAX_RATE = 260


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) != 6:
        return (0, 0, 0)
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    clamped = tuple(max(0, min(255, int(channel))) for channel in rgb)
    return f"#{clamped[0]:02x}{clamped[1]:02x}{clamped[2]:02x}"


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
    ) -> None:
        super().__init__(master, highlightthickness=0, bd=0, relief="flat", bg=master.cget("bg"))
        self.radius = radius
        self.top_color = top_color
        self.bottom_color = bottom_color
        self.border_color = border_color
        self.padding = padding

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
        if width < 4 or height < 4:
            return

        _draw_rounded_vertical_gradient(
            self,
            1,
            1,
            width - 2,
            height - 2,
            self.radius,
            self.top_color,
            self.bottom_color,
            self.border_color,
            1,
            "card",
        )

        self.coords(self._content_item, self.padding, self.padding)
        self.itemconfigure(self._content_item, width=max(1, width - (self.padding * 2)))


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
        height: int = 40,
        font: tuple[str, int, str] | tuple[str, int] = ("Segoe UI", 10, "bold"),
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
        self._pressed = False
        self._hovered = False
        self.configure(cursor="hand2" if enabled else "arrow")
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
        if not self._enabled:
            return
        if event.num != 1:
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
            top = _blend(top, BG, 0.6)
            bottom = _blend(bottom, BG, 0.6)
            border = _blend(border, BG, 0.65)
            text = _blend(text, BG, 0.5)
        elif self._pressed:
            top = _blend(top, "#000000", 0.18)
            bottom = _blend(bottom, "#000000", 0.18)
        elif self._hovered:
            top = _blend(top, "#ffffff", 0.08)
            bottom = _blend(bottom, "#ffffff", 0.08)

        return top, bottom, border, text

    def _redraw(self) -> None:
        self.delete("btn")

        width = self.winfo_width()
        height = self.winfo_height()
        if width < 4 or height < 4:
            return

        top, bottom, border, text = self._resolved_colors()

        _draw_rounded_vertical_gradient(
            self,
            1,
            1,
            width - 2,
            height - 2,
            self._radius,
            top,
            bottom,
            border,
            1,
            "btn",
        )

        y_offset = 1 if self._pressed and self._enabled else 0
        self.create_text(
            width // 2,
            (height // 2) + y_offset,
            text=self._label,
            fill=text,
            font=self._font,
            tags="btn",
        )


class WindowsTTSApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Vocal Canvas")
        self.geometry("940x660")
        self.minsize(800, 560)
        self.configure(bg=BG)

        self.engine = None
        self.voices = []
        self.engine_error = ""
        self._initialize_engine()

        self.voice_var = tk.StringVar()
        self.rate_var = tk.IntVar(value=170)
        self.char_count_var = tk.StringVar(value="0 characters")

        self.preview_file = Path(tempfile.gettempdir()) / "vocal_canvas_windows_preview.wav"

        self._build_ui()
        self._load_voices()
        self._update_char_count()

    def _initialize_engine(self) -> None:
        if pyttsx3 is None:
            self.engine_error = f"pyttsx3 unavailable: {PYTTSX3_IMPORT_ERROR}"
            return

        try:
            self.engine = pyttsx3.init()
            self.voices = self.engine.getProperty("voices") or []
        except Exception as exc:
            self.engine = None
            self.voices = []
            self.engine_error = str(exc)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "VCW.TCombobox",
            fieldbackground=FIELD_BG,
            background=FIELD_BG,
            foreground=TEXT_PRIMARY,
            bordercolor=BORDER,
            arrowcolor=TEXT_PRIMARY,
            padding=7,
        )
        style.map(
            "VCW.TCombobox",
            fieldbackground=[("readonly", FIELD_BG)],
            selectbackground=[("readonly", FIELD_BG)],
            selectforeground=[("readonly", TEXT_PRIMARY)],
            foreground=[("readonly", TEXT_PRIMARY)],
        )

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=24)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(2, weight=1)

        tk.Label(
            outer,
            text="Vocal Canvas",
            bg=BG,
            fg=TEXT_PRIMARY,
            font=("Segoe UI", 30, "bold"),
        ).grid(row=0, column=0, sticky="w")

        tk.Label(
            outer,
            text="Full desktop studio with local voices, preview, and export.",
            bg=BG,
            fg=TEXT_SECONDARY,
            font=("Segoe UI", 11),
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        card = RoundedGradientCard(
            outer,
            radius=26,
            top_color=CARD_TOP,
            bottom_color=CARD_BOTTOM,
            border_color=BORDER,
            content_bg=CARD_INNER,
            padding=18,
        )
        card.grid(row=2, column=0, sticky="nsew")

        content = card.content
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        tk.Label(content, text="Script", bg=CARD_INNER, fg=TEXT_PRIMARY, font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, sticky="w", pady=(2, 6)
        )

        text_shell = RoundedGradientCard(
            content,
            radius=16,
            top_color=_blend(FIELD_BG, "#ffffff", 0.06),
            bottom_color=FIELD_BG,
            border_color=BORDER,
            content_bg=FIELD_BG,
            padding=1,
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
            font=("Segoe UI", 12),
            padx=12,
            pady=10,
            bg=FIELD_BG,
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief="flat",
        )
        self.text_box.grid(row=0, column=0, sticky="nsew")
        self.text_box.insert("1.0", DEFAULT_TEXT)
        self.text_box.bind("<KeyRelease>", lambda _event: self._update_char_count())

        meta_row = tk.Frame(content, bg=CARD_INNER)
        meta_row.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        meta_row.grid_columnconfigure(0, weight=1)

        self.char_count_label = tk.Label(
            meta_row,
            textvariable=self.char_count_var,
            bg=CARD_INNER,
            fg=TEXT_SECONDARY,
            font=("Segoe UI", 9, "bold"),
            anchor="e",
        )
        self.char_count_label.grid(row=0, column=0, sticky="e")

        controls = tk.Frame(content, bg=CARD_INNER)
        controls.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        controls.grid_columnconfigure(0, weight=1)
        controls.grid_columnconfigure(1, weight=1)

        tk.Label(controls, text="Voice", bg=CARD_INNER, fg=TEXT_PRIMARY, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(controls, text="Speed", bg=CARD_INNER, fg=TEXT_PRIMARY, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=1, sticky="w"
        )

        voice_shell = RoundedGradientCard(
            controls,
            radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.05),
            bottom_color=FIELD_BG,
            border_color=BORDER,
            content_bg=FIELD_BG,
            padding=2,
        )
        voice_shell.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(4, 0))
        voice_shell.configure(height=42)
        voice_shell.content.grid_columnconfigure(0, weight=1)

        self.voice_combo = ttk.Combobox(voice_shell.content, textvariable=self.voice_var, state="readonly", style="VCW.TCombobox")
        self.voice_combo.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        speed_shell = RoundedGradientCard(
            controls,
            radius=12,
            top_color=_blend(FIELD_BG, "#ffffff", 0.05),
            bottom_color=FIELD_BG,
            border_color=BORDER,
            content_bg=FIELD_BG,
            padding=4,
        )
        speed_shell.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        speed_shell.configure(height=42)
        speed_shell.content.grid_columnconfigure(0, weight=1)

        speed_wrap = tk.Frame(speed_shell.content, bg=FIELD_BG)
        speed_wrap.grid(row=0, column=0, sticky="ew")
        speed_wrap.grid_columnconfigure(0, weight=1)

        self.rate_scale = tk.Scale(
            speed_wrap,
            from_=MIN_RATE,
            to=MAX_RATE,
            orient="horizontal",
            variable=self.rate_var,
            bg=CARD_INNER,
            fg=TEXT_PRIMARY,
            highlightthickness=0,
            troughcolor=FIELD_BG,
            activebackground=SUCCESS,
            font=("Segoe UI", 9),
            relief="flat",
        )
        self.rate_scale.grid(row=0, column=0, sticky="ew")

        self.rate_label = tk.Label(
            speed_wrap,
            text="170",
            bg=CARD_INNER,
            fg=TEXT_SECONDARY,
            font=("Segoe UI", 9, "bold"),
        )
        self.rate_label.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.rate_var.trace_add("write", lambda *_: self.rate_label.config(text=str(self.rate_var.get())))

        self.generate_btn = RoundedGradientButton(
            content,
            text="Generate Audio",
            command=self.preview_audio,
            top_color=SUCCESS,
            bottom_color=BORDER,
            border_color=_blend(BORDER, "#ffffff", 0.14),
            text_color=TEXT_PRIMARY,
            radius=14,
            height=44,
            font=("Segoe UI", 11, "bold"),
        )
        self.generate_btn.grid(row=4, column=0, sticky="ew", pady=(12, 0))

        action_row = tk.Frame(content, bg=CARD_INNER)
        action_row.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        action_row.grid_columnconfigure(0, weight=1)
        action_row.grid_columnconfigure(1, weight=1)

        self.export_btn = RoundedGradientButton(
            action_row,
            text="Export WAV",
            command=self.export_audio,
            top_color=ACCENT,
            bottom_color=_blend(ACCENT, "#000000", 0.2),
            border_color=BORDER,
            text_color=TEXT_PRIMARY,
            radius=12,
            height=39,
            font=("Segoe UI", 10, "bold"),
        )
        self.export_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.clear_btn = RoundedGradientButton(
            action_row,
            text="Clear",
            command=self.clear_text,
            top_color=BORDER,
            bottom_color=SUCCESS,
            border_color=_blend(BORDER, "#ffffff", 0.12),
            text_color=TEXT_PRIMARY,
            radius=12,
            height=39,
            font=("Segoe UI", 10, "bold"),
        )
        self.clear_btn.grid(row=0, column=1, sticky="ew")

        status_shell = RoundedGradientCard(
            content,
            radius=12,
            top_color=_blend(CARD_INNER, "#ffffff", 0.05),
            bottom_color=_blend(CARD_INNER, "#000000", 0.08),
            border_color=_blend(BORDER, BG, 0.22),
            content_bg=CARD_INNER,
            padding=8,
        )
        status_shell.grid(row=6, column=0, sticky="ew", pady=(10, 2))
        status_shell.content.grid_columnconfigure(0, weight=1)

        self.status = tk.Label(
            status_shell.content,
            text="Ready.",
            bg=CARD_INNER,
            fg=TEXT_SECONDARY,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self.status.grid(row=0, column=0, sticky="ew")

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
        self.generate_btn.set_enabled(not busy)
        self.export_btn.set_enabled(not busy)
        self.clear_btn.set_enabled(not busy)

    def _load_voices(self) -> None:
        if self.engine is None:
            self.voice_combo["values"] = ["Unavailable"]
            self.voice_var.set("Unavailable")
            self._set_status("Speech engine unavailable in this environment.", "error")
            self.generate_btn.set_enabled(False)
            self.export_btn.set_enabled(False)
            messagebox.showwarning(
                "Speech Engine Unavailable",
                "Windows Speech API could not be initialized.\n\n"
                "This usually happens in compatibility layers like Whisky/Wine.\n"
                "The app UI will open, but speech generation/export is disabled.\n\n"
                f"Details: {self.engine_error or 'Unknown error'}",
            )
            return

        if not self.voices:
            self._set_status("No voices detected.", "error")
            return

        names = [v.name for v in self.voices]
        self.voice_combo["values"] = names

        preferred = next((name for name in names if "zira" in name.lower()), None)
        self.voice_var.set(preferred or names[0])

    def _selected_voice_id(self) -> str:
        selected_name = self.voice_var.get().strip()
        for voice in self.voices:
            if voice.name == selected_name:
                return voice.id
        return self.voices[0].id if self.voices else ""

    def _update_char_count(self) -> None:
        count = len(self.text_box.get("1.0", "end").strip())
        self.char_count_var.set(f"{count} characters")

    def _collect(self) -> tuple[str, str, int] | None:
        if self.engine is None:
            messagebox.showerror(
                "Speech unavailable",
                "Speech generation is disabled because the Windows speech engine failed to initialize.\n\n"
                f"Details: {self.engine_error or 'Unknown error'}",
            )
            return None

        text = self.text_box.get("1.0", "end").strip()
        voice_id = self._selected_voice_id()
        rate = int(self.rate_var.get())

        if not text:
            messagebox.showerror("Missing text", "Please enter text to convert.")
            return None
        if not voice_id:
            messagebox.showerror("Missing voice", "No system voice available.")
            return None
        if not MIN_RATE <= rate <= MAX_RATE:
            messagebox.showerror("Invalid speed", f"Speed must be between {MIN_RATE} and {MAX_RATE}.")
            return None

        return text, voice_id, rate

    def _render(self, text: str, voice_id: str, rate: int, output: Path) -> None:
        self.engine.setProperty("voice", voice_id)
        self.engine.setProperty("rate", rate)
        self.engine.save_to_file(text, str(output))
        self.engine.runAndWait()

    def clear_text(self) -> None:
        self.text_box.delete("1.0", "end")
        self._update_char_count()
        self._set_status("Ready.")

    def preview_audio(self) -> None:
        payload = self._collect()
        if not payload:
            return

        text, voice_id, rate = payload
        self._set_busy(True)
        self._set_status("Generating preview...", "loading")
        self.update_idletasks()

        try:
            self._render(text, voice_id, rate, self.preview_file)
            winsound.PlaySound(str(self.preview_file), winsound.SND_FILENAME | winsound.SND_ASYNC)
            self._set_status("Preview ready and playing.", "success")
        except Exception as exc:
            messagebox.showerror("Preview failed", str(exc))
            self._set_status("Preview failed.", "error")
        finally:
            self._set_busy(False)

    def export_audio(self) -> None:
        payload = self._collect()
        if not payload:
            return

        text, voice_id, rate = payload
        save_path = filedialog.asksaveasfilename(
            title="Save speech as...",
            defaultextension=".wav",
            initialfile="vocal_canvas.wav",
            filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")],
        )
        if not save_path:
            return

        output_path = Path(save_path)
        self._set_busy(True)
        self._set_status("Exporting file...", "loading")
        self.update_idletasks()

        try:
            self._render(text, voice_id, rate, output_path)
            self._set_status(f"Saved to {output_path.name}.", "success")
            messagebox.showinfo("Saved", f"Audio exported to:\n{output_path}")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            self._set_status("Export failed.", "error")
        finally:
            self._set_busy(False)


def main() -> int:
    app = WindowsTTSApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
