from __future__ import annotations

import hmac
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for

try:
    from gtts import gTTS
except Exception:
    gTTS = None

APP_ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = APP_ROOT / "templates"
STATIC_DIR = APP_ROOT / "static"
OUTPUT_DIR = APP_ROOT / "generated_audio"
BUILD_DIR = APP_ROOT / "build"
DOWNLOAD_DIR = APP_ROOT / "downloads"
DESKTOP_SOURCE_DIR = APP_ROOT / "desktop_app"
WINDOWS_SOURCE_DIR = APP_ROOT / "windows_app"

PROJECT_ROOT = "/projects/vocal-canvas"
DEV_AUTH_SESSION_KEY = "vocal_canvas_dev_auth"

APP_BUNDLE_NAME = "Vocal Canvas.app"
DMG_NAME = "VocalCanvas.dmg"
WINDOWS_ZIP_NAME = "VocalCanvasWindows.zip"
APP_BUNDLE_PATH = BUILD_DIR / APP_BUNDLE_NAME
DMG_PATH = DOWNLOAD_DIR / DMG_NAME
WINDOWS_ZIP_PATH = DOWNLOAD_DIR / WINDOWS_ZIP_NAME

DEMO_MAX_CHARS = 200
OUTPUT_EXTENSIONS = ("wav", "mp3")

OUTPUT_DIR.mkdir(exist_ok=True)
BUILD_DIR.mkdir(exist_ok=True)
DOWNLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", os.getenv("SECRET_KEY", "vocal-canvas-local-secret"))

DEV_MODE_PASSWORD = os.getenv("VOCAL_CANVAS_DEV_PASSWORD", os.getenv("DEV_MODE_PASSWORD", "")).strip()

VOICE_CACHE: list[str] | None = None


def _have_required_tools() -> bool:
    return shutil.which("say") is not None and shutil.which("afconvert") is not None


def _is_dev_mode_enabled() -> bool:
    return bool(DEV_MODE_PASSWORD)


def _is_dev_mode_authenticated() -> bool:
    return bool(session.get(DEV_AUTH_SESSION_KEY))


def _safe_dev_next(next_path: str | None) -> str:
    if next_path and next_path.startswith(f"{PROJECT_ROOT}/dev"):
        return next_path
    return url_for("project_dev_home_page")


def _require_dev_mode():
    if not _is_dev_mode_enabled():
        abort(404)
    if not _is_dev_mode_authenticated():
        return redirect(url_for("project_dev_login_page", next=request.path))
    return None


def _have_cloud_tts() -> bool:
    return gTTS is not None


def _demo_mode() -> str:
    if _have_required_tools():
        return "macos"
    if _have_cloud_tts():
        return "cloud"
    return "unavailable"


def _parse_voices() -> list[str]:
    """Get available macOS voice names from `say -v ?`."""
    global VOICE_CACHE
    if VOICE_CACHE is not None:
        return VOICE_CACHE

    if shutil.which("say") is None:
        VOICE_CACHE = []
        return VOICE_CACHE

    output = subprocess.check_output(["say", "-v", "?"], text=True)
    voices: list[str] = []
    for line in output.splitlines():
        line = line.rstrip()
        if not line:
            continue
        parts = re.split(r"\s{2,}", line, maxsplit=2)
        if parts and parts[0] and parts[0] not in voices:
            voices.append(parts[0])

    VOICE_CACHE = voices
    return VOICE_CACHE


def _default_voice(voices: list[str]) -> str:
    preferred = ["Samantha", "Daniel", "Alex"]
    for voice in preferred:
        if voice in voices:
            return voice
    return voices[0] if voices else ""


def _cleanup_old_outputs(max_age_seconds: int = 12 * 60 * 60) -> None:
    now = time.time()
    for ext in OUTPUT_EXTENSIONS:
        pattern = f"*.{ext}"
        for path in OUTPUT_DIR.glob(pattern):
            try:
                if now - path.stat().st_mtime > max_age_seconds:
                    path.unlink(missing_ok=True)
            except OSError:
                continue


def _list_source_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []

    source_files: list[Path] = []
    for file_path in sorted(folder.rglob("*")):
        if file_path.is_file():
            source_files.append(file_path)

    return source_files


def _artifact_needs_refresh(artifact_path: Path, source_paths: list[Path]) -> bool:
    if not artifact_path.exists():
        return True

    artifact_mtime = artifact_path.stat().st_mtime
    for source in source_paths:
        if source.exists() and source.stat().st_mtime > artifact_mtime:
            return True

    return False


def _build_macos_app_bundle() -> Path:
    source_script = DESKTOP_SOURCE_DIR / "vocal_canvas_desktop.py"
    if not source_script.exists():
        raise FileNotFoundError("desktop_app/vocal_canvas_desktop.py is missing.")

    source_files = _list_source_files(DESKTOP_SOURCE_DIR)
    source_files.append(Path(__file__))
    if not _artifact_needs_refresh(APP_BUNDLE_PATH, source_files):
        return APP_BUNDLE_PATH

    if APP_BUNDLE_PATH.exists():
        shutil.rmtree(APP_BUNDLE_PATH)

    contents_dir = APP_BUNDLE_PATH / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"
    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    bundled_script = resources_dir / "vocal_canvas_desktop.py"
    shutil.copy2(source_script, bundled_script)

    readme_file = DESKTOP_SOURCE_DIR / "README.md"
    if readme_file.exists():
        shutil.copy2(readme_file, resources_dir / "README.md")

    launcher_file = macos_dir / "Vocal Canvas"
    launcher_file.write_text(
        "#!/bin/bash\n"
        "set -u\n"
        "SCRIPT_DIR=\"$(cd \"$(dirname \"$0\")\" && pwd)\"\n"
        "APP_ROOT=\"$(cd \"$SCRIPT_DIR/..\" && pwd)\"\n"
        "RESOURCES_DIR=\"$APP_ROOT/Resources\"\n"
        "LOG_DIR=\"$HOME/Library/Logs/VocalCanvas\"\n"
        "mkdir -p \"$LOG_DIR\"\n"
        "LOG_FILE=\"$LOG_DIR/launcher.log\"\n"
        "exec >>\"$LOG_FILE\" 2>&1\n"
        "echo \"==== $(date) : Launcher start ====\"\n"
        "PATH=\"/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}\"\n"
        "PYTHON_BIN=\"\"\n"
        "PYTHON_CANDIDATES=(\"/Library/Frameworks/Python.framework/Versions/3.14/bin/python3\" \"/usr/bin/python3\" \"$(command -v python3 2>/dev/null || true)\")\n"
        "for candidate in \"${PYTHON_CANDIDATES[@]}\"; do\n"
        "  if [ -n \"$candidate\" ] && [ -x \"$candidate\" ]; then\n"
        "    PYTHON_BIN=\"$candidate\"\n"
        "    break\n"
        "  fi\n"
        "done\n"
        "if [ -z \"$PYTHON_BIN\" ]; then\n"
        "  echo \"No usable python3 interpreter found.\"\n"
        "  /usr/bin/osascript -e 'display alert \"Vocal Canvas failed to launch\" message \"No Python 3 interpreter was found. See ~/Library/Logs/VocalCanvas/launcher.log\" as critical'\n"
        "  exit 1\n"
        "fi\n"
        "echo \"Using interpreter: $PYTHON_BIN\"\n"
        "\"$PYTHON_BIN\" \"$RESOURCES_DIR/vocal_canvas_desktop.py\"\n"
        "STATUS=$?\n"
        "echo \"Desktop app exited with status: $STATUS\"\n"
        "if [ $STATUS -ne 0 ]; then\n"
        "  /usr/bin/osascript -e 'display alert \"Vocal Canvas exited unexpectedly\" message \"Check ~/Library/Logs/VocalCanvas for details.\" as critical'\n"
        "fi\n"
        "exit $STATUS\n"
    )
    launcher_file.chmod(0o755)

    plist_file = contents_dir / "Info.plist"
    plist_file.write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
        "\"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
        "<plist version=\"1.0\">\n"
        "<dict>\n"
        "  <key>CFBundleName</key>\n"
        "  <string>Vocal Canvas</string>\n"
        "  <key>CFBundleDisplayName</key>\n"
        "  <string>Vocal Canvas</string>\n"
        "  <key>CFBundleIdentifier</key>\n"
        "  <string>com.vocalcanvas.desktop</string>\n"
        "  <key>CFBundleVersion</key>\n"
        "  <string>1.1</string>\n"
        "  <key>CFBundleShortVersionString</key>\n"
        "  <string>1.1</string>\n"
        "  <key>CFBundlePackageType</key>\n"
        "  <string>APPL</string>\n"
        "  <key>CFBundleExecutable</key>\n"
        "  <string>Vocal Canvas</string>\n"
        "  <key>LSMinimumSystemVersion</key>\n"
        "  <string>12.0</string>\n"
        "</dict>\n"
        "</plist>\n"
    )

    return APP_BUNDLE_PATH


def _build_desktop_dmg() -> Path:
    # On non-macOS deploy targets, serve an existing prebuilt DMG if present.
    if shutil.which("hdiutil") is None:
        if DMG_PATH.exists():
            return DMG_PATH
        raise RuntimeError("hdiutil is not available on this machine.")

    app_bundle = _build_macos_app_bundle()
    if not _artifact_needs_refresh(DMG_PATH, [app_bundle]):
        return DMG_PATH

    staging_dir = BUILD_DIR / "dmg_staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    staged_app = staging_dir / APP_BUNDLE_NAME
    shutil.copytree(app_bundle, staged_app)

    applications_link = staging_dir / "Applications"
    if applications_link.exists() or applications_link.is_symlink():
        applications_link.unlink(missing_ok=True)
    applications_link.symlink_to("/Applications")

    temp_dmg = DMG_PATH.with_suffix(".tmp.dmg")
    temp_dmg.unlink(missing_ok=True)

    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            "Vocal Canvas",
            "-srcfolder",
            str(staging_dir),
            "-ov",
            "-format",
            "UDZO",
            str(temp_dmg),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    temp_dmg.replace(DMG_PATH)
    return DMG_PATH


def _build_windows_zip() -> Path:
    source_script = WINDOWS_SOURCE_DIR / "vocal_canvas_windows.py"
    if not source_script.exists():
        raise FileNotFoundError("windows_app/vocal_canvas_windows.py is missing.")

    source_files = _list_source_files(WINDOWS_SOURCE_DIR)
    source_files.append(Path(__file__))
    if not _artifact_needs_refresh(WINDOWS_ZIP_PATH, source_files):
        return WINDOWS_ZIP_PATH

    temp_zip = WINDOWS_ZIP_PATH.with_suffix(".tmp.zip")
    temp_zip.unlink(missing_ok=True)

    with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for source_path in source_files:
            if source_path.parent == WINDOWS_SOURCE_DIR or WINDOWS_SOURCE_DIR in source_path.parents:
                relative_name = source_path.relative_to(WINDOWS_SOURCE_DIR)
                archive_name = Path("VocalCanvasWindows") / relative_name
                archive.write(source_path, archive_name.as_posix())

    temp_zip.replace(WINDOWS_ZIP_PATH)
    return WINDOWS_ZIP_PATH


def _render_to_wav(text: str, voice: str, rate: int, prefix: str = "demo") -> Path:
    unique_id = f"{int(time.time())}_{secrets.token_hex(4)}"
    output_file = OUTPUT_DIR / f"{prefix}_{unique_id}.wav"

    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        subprocess.run(
            ["say", "-v", voice, "-r", str(rate), text, "-o", str(temp_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["afconvert", str(temp_path), str(output_file), "-f", "WAVE", "-d", "LEI16"],
            check=True,
            capture_output=True,
            text=True,
        )
        return output_file
    finally:
        temp_path.unlink(missing_ok=True)


def _render_to_mp3(text: str, prefix: str = "demo") -> Path:
    if gTTS is None:
        raise RuntimeError("Cloud TTS dependency is unavailable.")

    unique_id = f"{int(time.time())}_{secrets.token_hex(4)}"
    output_file = OUTPUT_DIR / f"{prefix}_{unique_id}.mp3"
    tts = gTTS(text=text, lang="en")
    tts.save(str(output_file))
    return output_file


def _artifact_build_id(path: Path) -> int:
    if not path.exists():
        return 0
    return int(path.stat().st_mtime)


def _apply_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _handle_demo_speak():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"error": "Enter text before generating demo audio."}), 400
    if len(text) > DEMO_MAX_CHARS:
        return jsonify({"error": f"Demo is limited to {DEMO_MAX_CHARS} characters."}), 400

    mode = _demo_mode()
    chosen_voice = "Cloud"
    rate: int | None = None

    if mode == "macos":
        voices = _parse_voices()
        chosen_voice = str(payload.get("voice", "")).strip()
        if chosen_voice not in voices:
            chosen_voice = _default_voice(voices)

        if not chosen_voice:
            return jsonify({"error": "No voices found on this machine."}), 500

        try:
            rate = int(payload.get("rate", 170))
        except (TypeError, ValueError):
            return jsonify({"error": "Rate must be a number between 80 and 400."}), 400

        if not 80 <= rate <= 400:
            return jsonify({"error": "Rate must be between 80 and 400."}), 400

        try:
            output_file = _render_to_wav(text=text, voice=chosen_voice, rate=rate, prefix="demo")
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            return jsonify({"error": "Failed to generate demo speech.", "detail": detail}), 500
    elif mode == "cloud":
        try:
            output_file = _render_to_mp3(text=text, prefix="demo")
        except Exception as exc:
            return jsonify({"error": "Failed to generate demo speech.", "detail": str(exc)}), 500
    else:
        return jsonify({"error": "Demo audio is unavailable on this server."}), 500

    _cleanup_old_outputs()
    response_payload = {
        "audio_url": url_for("project_serve_audio", filename=output_file.name),
        "voice": chosen_voice,
        "characters": len(text),
        "format": output_file.suffix.lstrip(".").lower(),
    }
    if rate is not None:
        response_payload["rate"] = rate

    return jsonify(response_payload)


def _demo_view_context() -> dict[str, object]:
    voices = _parse_voices()
    return {
        "voices": voices,
        "default_voice": _default_voice(voices),
        "demo_mode": _demo_mode(),
        "demo_limit": DEMO_MAX_CHARS,
    }


def _download_view_context() -> dict[str, object]:
    mac_buildable = DMG_PATH.exists() or (
        (DESKTOP_SOURCE_DIR / "vocal_canvas_desktop.py").exists() and shutil.which("hdiutil") is not None
    )
    windows_buildable = WINDOWS_ZIP_PATH.exists() or (WINDOWS_SOURCE_DIR / "vocal_canvas_windows.py").exists()
    return {
        "mac_buildable": mac_buildable,
        "windows_buildable": windows_buildable,
        "mac_filename": DMG_NAME,
        "windows_filename": WINDOWS_ZIP_NAME,
        "mac_build_id": _artifact_build_id(DMG_PATH),
        "windows_build_id": _artifact_build_id(WINDOWS_ZIP_PATH),
    }


@app.context_processor
def inject_global_template_data():
    return {
        "dev_mode_enabled": _is_dev_mode_enabled(),
    }


@app.get("/")
def projects_hub():
    return render_template("projects_hub.html")


@app.get("/projects")
def projects_hub_alias():
    return redirect(url_for("projects_hub"))


@app.get(PROJECT_ROOT)
def project_root_redirect():
    return redirect(url_for("project_home_page"))


@app.get(f"{PROJECT_ROOT}/home")
def project_home_page():
    return render_template("home.html", active_tab="home")


@app.get(f"{PROJECT_ROOT}/demo")
def project_demo_page():
    return render_template(
        "demo.html",
        active_tab="demo",
        **_demo_view_context(),
    )


@app.get(f"{PROJECT_ROOT}/qa")
def project_qa_page():
    return render_template("qa.html", active_tab="qa")


@app.get(f"{PROJECT_ROOT}/download")
def project_download_page():
    return render_template(
        "download.html",
        active_tab="download",
        **_download_view_context(),
    )


@app.get(f"{PROJECT_ROOT}/dev")
def project_dev_entry():
    if not _is_dev_mode_enabled():
        abort(404)
    if _is_dev_mode_authenticated():
        return redirect(url_for("project_dev_home_page"))
    return redirect(url_for("project_dev_login_page"))


@app.get(f"{PROJECT_ROOT}/dev/login")
def project_dev_login_page():
    if not _is_dev_mode_enabled():
        abort(404)
    if _is_dev_mode_authenticated():
        return redirect(url_for("project_dev_home_page"))

    return render_template(
        "dev_login.html",
        next_path=_safe_dev_next(request.args.get("next")),
        error_message="",
    )


@app.post(f"{PROJECT_ROOT}/dev/login")
def project_dev_login_submit():
    if not _is_dev_mode_enabled():
        abort(404)
    if _is_dev_mode_authenticated():
        return redirect(url_for("project_dev_home_page"))

    supplied_password = str(request.form.get("password", ""))
    next_path = _safe_dev_next(request.form.get("next"))

    if hmac.compare_digest(supplied_password, DEV_MODE_PASSWORD):
        session[DEV_AUTH_SESSION_KEY] = True
        return redirect(next_path)

    return render_template(
        "dev_login.html",
        next_path=next_path,
        error_message="Wrong password. Try again.",
    )


@app.post(f"{PROJECT_ROOT}/dev/logout")
def project_dev_logout():
    if not _is_dev_mode_enabled():
        abort(404)
    session.pop(DEV_AUTH_SESSION_KEY, None)
    return redirect(url_for("project_dev_login_page"))


@app.get(f"{PROJECT_ROOT}/dev/home")
def project_dev_home_page():
    maybe_redirect = _require_dev_mode()
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template("dev_home.html", active_dev_tab="home")


@app.get(f"{PROJECT_ROOT}/dev/demo")
def project_dev_demo_page():
    maybe_redirect = _require_dev_mode()
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template("dev_demo.html", active_dev_tab="demo", **_demo_view_context())


@app.get(f"{PROJECT_ROOT}/dev/qa")
def project_dev_qa_page():
    maybe_redirect = _require_dev_mode()
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template("dev_qa.html", active_dev_tab="qa")


@app.get(f"{PROJECT_ROOT}/dev/download")
def project_dev_download_page():
    maybe_redirect = _require_dev_mode()
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template("dev_download.html", active_dev_tab="download", **_download_view_context())


@app.get(f"{PROJECT_ROOT}/dev/copy/home")
def project_dev_copy_home_page():
    maybe_redirect = _require_dev_mode()
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template("dev_copy_home.html", active_dev_tab="home", active_copy_tab="home")


@app.get(f"{PROJECT_ROOT}/dev/copy/demo")
def project_dev_copy_demo_page():
    maybe_redirect = _require_dev_mode()
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template(
        "dev_copy_demo.html",
        active_dev_tab="demo",
        active_copy_tab="demo",
        **_demo_view_context(),
    )


@app.get(f"{PROJECT_ROOT}/dev/copy/qa")
def project_dev_copy_qa_page():
    maybe_redirect = _require_dev_mode()
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template("dev_copy_qa.html", active_dev_tab="qa", active_copy_tab="qa")


@app.get(f"{PROJECT_ROOT}/dev/copy/download")
def project_dev_copy_download_page():
    maybe_redirect = _require_dev_mode()
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template(
        "dev_copy_download.html",
        active_dev_tab="download",
        active_copy_tab="download",
        **_download_view_context(),
    )


@app.post(f"{PROJECT_ROOT}/api/demo-speak")
def project_demo_speak_api():
    return _handle_demo_speak()


@app.get(f"{PROJECT_ROOT}/audio/<path:filename>")
def project_serve_audio(filename: str):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=False)


@app.get(f"{PROJECT_ROOT}/download/macos")
def project_download_macos():
    try:
        dmg_path = _build_desktop_dmg()
    except Exception as exc:
        return jsonify({"error": "macOS installer is unavailable.", "detail": str(exc)}), 500

    response = send_file(dmg_path, as_attachment=True, download_name=dmg_path.name)
    return _apply_no_cache_headers(response)


@app.get(f"{PROJECT_ROOT}/download/windows")
def project_download_windows():
    try:
        zip_path = _build_windows_zip()
    except Exception as exc:
        return jsonify({"error": "Windows package is unavailable.", "detail": str(exc)}), 500

    response = send_file(zip_path, as_attachment=True, download_name=zip_path.name)
    return _apply_no_cache_headers(response)


# Legacy aliases
@app.get("/home")
def home_page_legacy():
    return redirect(url_for("project_home_page"))


@app.get("/demo")
def demo_page_legacy():
    return redirect(url_for("project_demo_page"))


@app.get("/qa")
def qa_page_legacy():
    return redirect(url_for("project_qa_page"))


@app.get("/download")
def download_page_legacy():
    return redirect(url_for("project_download_page"))


@app.get("/dev")
def dev_page_legacy():
    return redirect(url_for("project_dev_entry"))


@app.post("/api/demo-speak")
def demo_speak_legacy():
    return _handle_demo_speak()


@app.get("/audio/<path:filename>")
def serve_audio_legacy(filename: str):
    return project_serve_audio(filename)


@app.get("/download/macos")
def download_macos_legacy():
    return project_download_macos()


@app.get("/download/windows")
def download_windows_legacy():
    return project_download_windows()


@app.get("/download/desktop")
def download_desktop_alias():
    return project_download_macos()


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", os.getenv("FLASK_PORT", "5050")))
    debug = os.getenv("FLASK_DEBUG", "1").strip().lower() in {"1", "true", "yes", "on"}
    app.run(host=host, port=port, debug=debug)
