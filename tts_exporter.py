import re
import os
import subprocess
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

# ---------------- Helpers ----------------

def run_stdout(cmd: list[str]) -> str:
    """Run a command and return stdout; raise on failure."""
    return subprocess.check_output(cmd, text=True).strip()

def have_lame() -> bool:
    """Check whether lame is available on PATH."""
    try:
        run_stdout(["lame", "--version"])
        return True
    except Exception:
        return False

def parse_say_voices() -> list[str]:
    """
    Return the full voice names from `say -v "?"`.
    This correctly keeps names with spaces/parentheses by splitting on 2+ spaces.
    """
    out = subprocess.check_output(["say", "-v", "?"], text=True)
    voices: list[str] = []
    for line in out.splitlines():
        line = line.rstrip()
        if not line:
            continue
        # Format: "<VOICE NAME>  <LOCALE>  <COMMENT>"
        parts = re.split(r"\s{2,}", line, maxsplit=2)
        if parts and parts[0]:
            voices.append(parts[0])

    # Deduplicate preserving order
    seen = set()
    uniq = []
    for v in voices:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq

def group_voice_variants(full_voice_names: list[str]) -> dict[str, list[str]]:
    """
    Group voices by a "base name", splitting on the first " (".
    Examples:
      "Daniel" -> base="Daniel", variant="Default"
      "Daniel (UK)" -> base="Daniel", variant="(UK)"
      "Siri Voice 4" -> base="Siri Voice 4", variant="Default"
      "Samantha (Enhanced)" -> base="Samantha", variant="(Enhanced)"
    Note: macOS varies. We simply group by this pattern.
    """
    grouped: dict[str, list[str]] = {}

    for full in full_voice_names:
        if " (" in full and full.endswith(")"):
            base = full.split(" (", 1)[0]
            suffix = full[len(base):]  # includes the leading space: " (UK)"
            variant = suffix.strip()   # "(UK)"
        else:
            base = full
            variant = "Default"

        grouped.setdefault(base, []).append(variant)

    # Sort variants: Default first, then alphabetically
    for base, variants in grouped.items():
        variants_unique = []
        seen = set()
        for v in variants:
            if v not in seen:
                seen.add(v)
                variants_unique.append(v)

        variants_unique.sort(key=lambda x: (0 if x == "Default" else 1, x.lower()))
        grouped[base] = variants_unique

    return grouped

def reconstruct_full_voice(base: str, variant: str) -> str:
    """Turn (base, variant) back into the full voice name used by `say -v`."""
    if variant == "Default":
        return base
    # variant looks like "(UK)" or "(Enhanced)" etc.
    return f"{base} {variant}"

def safe_filename(name: str) -> str:
    """
    Very light cleanup: remove forbidden path chars.
    (macOS allows many chars, but this avoids accidental slashes.)
    """
    name = name.strip()
    name = name.replace("/", "-").replace("\\", "-").replace(":", "-")
    return name

def ensure_extension(filename: str, ext: str) -> str:
    filename = filename.strip()
    if not filename:
        filename = "tts_export"
    filename = safe_filename(filename)
    if not filename.lower().endswith("." + ext.lower()):
        filename += "." + ext
    return filename

# ---------------- Export logic ----------------

def export_tts():
    text = text_box.get("1.0", "end").strip()
    if not text:
        messagebox.showerror("No text", "Please enter some text to speak.")
        return

    base = base_voice_var.get().strip()
    variant = variant_var.get().strip()
    if not base or not variant:
        messagebox.showerror("No voice", "Please choose a voice and a version.")
        return

    full_voice = reconstruct_full_voice(base, variant)

    fmt = fmt_var.get().lower().strip()
    if fmt not in {"mp3", "m4a", "wav", "aiff", "caf"}:
        messagebox.showerror("Invalid format", "Please choose a valid format.")
        return

    # speech rate
    try:
        rate = int(rate_var.get())
        if not (80 <= rate <= 400):
            raise ValueError
    except Exception:
        messagebox.showerror("Invalid rate", "Rate must be a number between 80 and 400.")
        return

    # file name input
    filename_input = filename_var.get().strip()
    out_name = ensure_extension(filename_input, fmt)

    # choose folder+file
    path = filedialog.asksaveasfilename(
        title="Save audio as…",
        initialfile=out_name,
        defaultextension="." + fmt,
        filetypes=[
            ("MP3 audio", "*.mp3"),
            ("M4A audio (AAC)", "*.m4a"),
            ("WAV audio", "*.wav"),
            ("AIFF audio", "*.aiff"),
            ("CAF audio", "*.caf"),
            ("All files", "*.*"),
        ],
    )
    if not path:
        return

    out_path = Path(path)

    tmp_aiff = None
    try:
        # Always render to temp AIFF first; it's reliable as an intermediate.
        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
            tmp_aiff = tmp.name

        # Important: full_voice may include spaces/parentheses. This call handles it correctly.
        subprocess.check_call(["say", "-v", full_voice, "-r", str(rate), text, "-o", tmp_aiff])

        if fmt == "mp3":
            if not have_lame():
                messagebox.showerror(
                    "MP3 encoder missing",
                    "MP3 export needs LAME.\n\nInstall it with:\n  brew install lame\n\n"
                    "Or pick M4A/WAV/AIFF instead."
                )
                return
            # High-quality VBR (recommended):
            subprocess.check_call(["lame", "-V2", tmp_aiff, str(out_path)])

        elif fmt == "m4a":
            subprocess.check_call(["afconvert", tmp_aiff, str(out_path), "-f", "mp4f", "-d", "aac"])

        elif fmt == "wav":
            subprocess.check_call(["afconvert", tmp_aiff, str(out_path), "-f", "WAVE", "-d", "LEI16"])

        elif fmt == "aiff":
            os.replace(tmp_aiff, str(out_path))
            tmp_aiff = None  # prevent deletion

        elif fmt == "caf":
            subprocess.check_call(["afconvert", tmp_aiff, str(out_path), "-f", "caff"])

        messagebox.showinfo(
            "Done",
            f"Saved:\n{out_path}\n\nVoice: {full_voice}\nRate: {rate}\nFormat: {fmt}"
        )

    except subprocess.CalledProcessError as e:
        messagebox.showerror("Error", f"Command failed:\n{e}")
    except Exception as e:
        messagebox.showerror("Error", f"Unexpected error:\n{e}")
    finally:
        if tmp_aiff and os.path.exists(tmp_aiff):
            try:
                os.remove(tmp_aiff)
            except Exception:
                pass

# ---------------- UI callbacks ----------------

def refresh_variant_dropdown(*_):
    base = base_voice_var.get().strip()
    if not base:
        variant_combo["values"] = []
        variant_var.set("")
        return

    variants = VOICE_GROUPS.get(base, ["Default"])
    variant_combo["values"] = variants

    # Prefer Enhanced/Premium/UK/etc if available, otherwise Default
    preferred_order = ["(Enhanced)", "(Premium)", "(UK)", "Default"]
    for pref in preferred_order:
        if pref in variants:
            variant_var.set(pref)
            break
    else:
        variant_var.set(variants[0])

def on_format_change(*_):
    # Keep the filename extension in sync with chosen format (nice UX)
    fmt = fmt_var.get().lower().strip()
    name = filename_var.get().strip()
    if not name:
        return
    # Replace existing extension if it looks like one of our supported formats
    m = re.match(r"^(.*)\.(mp3|m4a|wav|aiff|caf)$", name, flags=re.IGNORECASE)
    if m:
        filename_var.set(m.group(1) + "." + fmt)

# ---------------- Build app ----------------

root = tk.Tk()
root.title("macOS TTS Exporter")

main = ttk.Frame(root, padding=12)
main.grid(row=0, column=0, sticky="nsew")

root.columnconfigure(0, weight=1)
root.rowconfigure(0, weight=1)
main.columnconfigure(0, weight=1)

# Row 0: Voice selectors (side-by-side)
voice_row = ttk.Frame(main)
voice_row.grid(row=0, column=0, sticky="ew")
voice_row.columnconfigure(0, weight=1)
voice_row.columnconfigure(1, weight=1)

ttk.Label(voice_row, text="Voice:").grid(row=0, column=0, sticky="w", padx=(0, 8))
ttk.Label(voice_row, text="Version:").grid(row=0, column=1, sticky="w")

base_voice_var = tk.StringVar()
variant_var = tk.StringVar()

base_combo = ttk.Combobox(voice_row, textvariable=base_voice_var, state="readonly")
variant_combo = ttk.Combobox(voice_row, textvariable=variant_var, state="readonly")

base_combo.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, 10))
variant_combo.grid(row=1, column=1, sticky="ew", pady=(0, 10))

# Row 1: Format + Rate (side-by-side)
opts_row = ttk.Frame(main)
opts_row.grid(row=1, column=0, sticky="ew")
opts_row.columnconfigure(0, weight=1)
opts_row.columnconfigure(1, weight=1)

ttk.Label(opts_row, text="Format:").grid(row=0, column=0, sticky="w", padx=(0, 8))
ttk.Label(opts_row, text="Rate (80–400):").grid(row=0, column=1, sticky="w")

fmt_var = tk.StringVar(value="mp3")
fmt_combo = ttk.Combobox(opts_row, textvariable=fmt_var, state="readonly",
                         values=["mp3", "m4a", "wav", "aiff", "caf"])
fmt_combo.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, 10))

rate_var = tk.StringVar(value="175")
rate_entry = ttk.Entry(opts_row, textvariable=rate_var)
rate_entry.grid(row=1, column=1, sticky="ew", pady=(0, 10))

# Row 2: Filename
ttk.Label(main, text="File name:").grid(row=2, column=0, sticky="w")
filename_var = tk.StringVar(value="tts_export.mp3")
filename_entry = ttk.Entry(main, textvariable=filename_var)
filename_entry.grid(row=3, column=0, sticky="ew", pady=(0, 10))

# Row 3: Text
ttk.Label(main, text="Text:").grid(row=4, column=0, sticky="w")
text_box = tk.Text(main, height=10, wrap="word")
text_box.grid(row=5, column=0, sticky="nsew")
main.rowconfigure(5, weight=1)

# Row 4: Buttons
btn_row = ttk.Frame(main)
btn_row.grid(row=6, column=0, sticky="ew", pady=(10, 0))
btn_row.columnconfigure(0, weight=1)

export_btn = ttk.Button(btn_row, text="Export…", command=export_tts)
export_btn.grid(row=0, column=0, sticky="ew")

# Load voices + set defaults
try:
    FULL_VOICES = parse_say_voices()
    VOICE_GROUPS = group_voice_variants(FULL_VOICES)

    base_names = sorted(VOICE_GROUPS.keys(), key=lambda s: s.lower())
    base_combo["values"] = base_names

    # Default base voice guess
    # Prefer Daniel if present, else Samantha, else first.
    if "Daniel" in VOICE_GROUPS:
        base_voice_var.set("Daniel")
    elif "Samantha" in VOICE_GROUPS:
        base_voice_var.set("Samantha")
    elif base_names:
        base_voice_var.set(base_names[0])
    else:
        base_voice_var.set("")

    refresh_variant_dropdown()

except Exception as e:
    VOICE_GROUPS = {}
    messagebox.showwarning("Voices", f"Could not load voices:\n{e}")

# Wire events
base_voice_var.trace_add("write", refresh_variant_dropdown)
fmt_var.trace_add("write", on_format_change)

# If lame not installed, default to m4a so it works instantly
if not have_lame():
    fmt_var.set("m4a")
    filename_var.set(ensure_extension(filename_var.get().replace(".mp3", ""), "m4a"))

root.minsize(560, 480)
root.mainloop()