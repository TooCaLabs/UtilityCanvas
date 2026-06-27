# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['sounddevice', 'numpy', 'faster_whisper', 'ctranslate2', 'huggingface_hub', 'tokenizers', 'tqdm'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Vocal Canvas',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Vocal Canvas',
)
app = BUNDLE(
    coll,
    name='Vocal Canvas.app',
    icon='/Users/goldknow/v3ts/New Project (2).icns',
    bundle_identifier='com.toocalabs.vocalcanvas',
    info_plist={
        'NSMicrophoneUsageDescription': 'Vocal Canvas uses the microphone to transcribe your speech in real time.',
    },
)
