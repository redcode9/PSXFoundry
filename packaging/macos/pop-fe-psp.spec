# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)
from spec_common import bundle_info, packaging_inputs


ROOT = Path(SPECPATH).parents[1]
GENERATED = ROOT / "build" / "macos" / "generated"
datas, binaries, hiddenimports = packaging_inputs(ROOT, "pop-fe-psp.ui")

a = Analysis(
    [str(ROOT / "pop-fe-psp.py")],
    pathex=[str(GENERATED), str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["scipy", "sklearn"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PSXFoundry PSP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PSXFoundry PSP",
)
app = BUNDLE(
    coll,
    name="PSXFoundry PSP.app",
    icon=os.environ["PSXFOUNDRY_ICON_PATH"],
    bundle_identifier="io.github.redcode9.psxfoundry.psp",
    info_plist=bundle_info("PSXFoundry PSP"),
)
