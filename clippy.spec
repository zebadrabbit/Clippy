# PyInstaller spec for a single-file clippy.exe.
#
# Why a spec and not a bare command line: the TUI stylesheet and the overlay
# font ship as package data, and a onefile build has to be told to carry them.
# Textual also loads widgets dynamically, so it needs collecting whole.
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = collect_data_files("clippy")
hiddenimports = []
for package in ("textual", "rich"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    hiddenimports += pkg_hidden

a = Analysis(
    ["clippy/__main__.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hiddenimports + ["clippy.tui.app", "yachalk", "yaml"],
    excludes=["tkinter", "matplotlib", "numpy", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="clippy",
    console=True,
    upx=False,
    strip=False,
)
