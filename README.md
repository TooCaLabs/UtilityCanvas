# Vocal Canvas

Vocal Canvas is a text-to-speech toolkit for creators with:

- A public website (Home, Demo, Q&A, Download)
- A full-featured downloadable desktop app
- macOS and Windows distribution packages

Project repository: [ARealGoldknow/UtilityCanvas](https://github.com/ARealGoldknow/UtilityCanvas)

## Version

`v0.1.1 (Beta)`

## Install

### macOS

1. Open the project website and go to the `Download` tab.
2. Download `VocalCanvas.dmg`.
3. Open the DMG and drag `Vocal Canvas.app` into `Applications`.
4. Launch the app from `Applications`.
5. If macOS warns on first launch, right-click the app, choose `Open`, then confirm.

### Windows

1. Open the project website and go to the `Download` tab.
2. Download `VocalCanvasWindows.zip`.
3. Extract the zip.
4. Install Python 3.10+ if not installed.
5. In the extracted folder, run:

```bash
pip install -r requirements.txt
python vocal_canvas_windows.py
```

## Features

- Multi-page website with animated navigation
- Quick online demo voice preview
- Desktop app with full controls:
  - System voice selection
  - Speed control
  - Audio generation and WAV export
- Download delivery for:
  - macOS `.dmg`
  - Windows `.zip`
- Unified dark theme across website and apps

## Beta Expectations

This is a beta release. Expect:

- Visual and layout changes between versions
- Ongoing tuning for installer behavior and first-launch flow
- Incomplete documentation in some sections (for example, Q&A)
- Fast iteration on UI details and quality-of-life features

If you find issues, open one on GitHub with:

- OS and version
- Exact step that failed
- Screenshot or error message
