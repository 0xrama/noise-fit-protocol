# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]

hiddenimports = []
hiddenimports += collect_submodules("bleak")
hiddenimports += [
    "webview.platforms.cocoa",
    "AppKit",
    "CoreBluetooth",
    "Foundation",
    "WebKit",
    "objc",
]


a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "web"), "web")],
    hiddenimports=hiddenimports,
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
    name="NoiseFit",
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
    name="NoiseFit",
)
app = BUNDLE(
    coll,
    name="NoiseFit.app",
    icon=None,
    bundle_identifier="app.noisefit.dashboard",
    info_plist={
        "CFBundleDisplayName": "NoiseFit",
        "CFBundleName": "NoiseFit",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "LSApplicationCategoryType": "public.app-category.healthcare-fitness",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSBluetoothAlwaysUsageDescription": "NoiseFit connects to your watch over Bluetooth to sync health data.",
        "NSBluetoothPeripheralUsageDescription": "NoiseFit connects to your watch over Bluetooth to sync health data.",
        "NSLocalNetworkUsageDescription": "NoiseFit uses a temporary local callback server when connecting Google Fit.",
    },
)
