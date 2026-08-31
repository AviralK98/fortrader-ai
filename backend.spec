# PyInstaller spec for the backend sidecar.
#
# Built as a one-directory bundle rather than one-file: a one-file build
# unpacks pandas and numpy into a temp directory on every launch, which
# adds seconds to startup each time the desktop app opens. The installer
# hides the directory from the user either way.
#
# Build with:  python -m PyInstaller backend.spec --noconfirm

from PyInstaller.utils.hooks import collect_submodules

# uvicorn resolves its loop, protocol and lifespan implementations by
# string at runtime, so static analysis cannot see them.
hidden = [
    *collect_submodules("uvicorn"),
    *collect_submodules("encodings"),
    "asyncio",
    "anyio._backends._asyncio",
]

analysis = Analysis(
    ["backend/main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trimmed to keep the bundle to a sane size. None of these are
    # imported by the backend; a missing one would surface immediately as
    # an ImportError on startup, which the smoke test below catches.
    excludes=[
        "tkinter",
        "matplotlib",
        "PIL",
        "PyQt5",
        "PySide2",
        "notebook",
        "IPython",
        "pytest",
        "mypy",
        "playwright",
        "scipy",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="fortrader-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No console window: the desktop app owns the UI and reads the
    # sidecar's output over the pipe.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="fortrader-backend",
)
