# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AcDec Flashcard Generator (Windows one-folder build)."""
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND_DIST = ROOT / "frontend" / "dist"

if not FRONTEND_DIST.joinpath("index.html").is_file():
    raise SystemExit(
        f"Frontend not built: {FRONTEND_DIST / 'index.html'} missing. "
        "Run: cd frontend && npm run build"
    )

datas = [(str(FRONTEND_DIST), "frontend_dist")]

hiddenimports = [
    "app",
    "app.main",
    "app.config",
    "app.paths",
    "app.licensing",
    "app.service",
    "app.db.database",
    "app.db.models",
    "app.generation.worker",
    "app.generation.providers",
    "app.generation.compile",
    "app.generation.prompt",
    "app.parsing.structure",
    "app.parsing.captions",
    "app.parsing.deterministic",
    "app.parsing.spans",
    "app.validation.runner",
    "app.validation.deterministic",
    "app.validation.ai_check",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "multipart",
    "cryptography",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "fitz",
    "pandas",
    "httpx",
    "anyio",
    "anyio._backends._asyncio",
    "starlette.routing",
    "fastapi",
    "pydantic",
]

excludes = [
    "pytest",
    "tkinter",
    "matplotlib",
    "IPython",
    "notebook",
]

a = Analysis(
    [str(BACKEND / "app" / "launcher.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AcDecFlashcards",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AcDecFlashcards",
)
