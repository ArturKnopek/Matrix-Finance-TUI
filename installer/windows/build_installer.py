"""
Buduje instalator Windows: dist/MatrixFinance-Setup-<wersja>.exe

Działa na Linuksie i Windows (potrzebne: Python 3.10+, pip, makensis z NSIS 3):
    Linux:   sudo apt install nsis
    Windows: winget install NSIS.NSIS
    python installer/windows/build_installer.py

Co robi:
 1. pobiera oficjalny Python dla Windows (pakiet NuGet „python” od PSF), sprawdza sumę SHA-256,
 2. usuwa z niego zbędne części (testy, IDLE, Tk, pip),
 3. instaluje biblioteki z requirements.txt w wersjach dla Windows (pip --platform win_amd64),
 4. kopiuje program, uruchamiacz i ikonę, prekompiluje pliki .py,
 5. wywołuje makensis (MatrixFinance.nsi) i zapisuje sumę SHA-256 instalatora.
"""

from __future__ import annotations

import argparse
import compileall
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from src.version import APP_VERSION  # noqa: E402

PYTHON_VERSION = "3.13.17"
# SHA-256 pakietu python.<wersja>.nupkg (weryfikacja pobranego pliku); inne wersje: --python X.Y.Z --no-verify
PYTHON_SHA256 = {
    "3.13.17": "dce409744b088f94c6e37ba41f8100c384c27e029e843237364c602d30d475e5",
}
NUGET_URL = "https://api.nuget.org/v3-flatcontainer/python/{v}/python.{v}.nupkg"

# z pakietu Pythona pomijamy (ścieżki względem tools/)
PY_EXCLUDE_PREFIXES = (
    "Lib/test/", "Lib/idlelib/", "Lib/tkinter/", "Lib/turtledemo/", "Lib/ensurepip/", "Lib/lib2to3/",
    "Lib/site-packages/pip", "Scripts/", "include/", "libs/", "tcl/", "Tools/",
    "DLLs/_tkinter.pyd", "DLLs/tcl", "DLLs/tk", "Lib/turtle.py",
)
APP_ITEMS = ["main.py", "src", "assets", "requirements.txt", "README.md"]


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def download_python(version: str, cache: Path, verify: bool) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"python.{version}.nupkg"
    if not target.exists():
        url = NUGET_URL.format(v=version)
        log(f"pobieranie {url}")
        with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 - stały adres https
            data = resp.read()
        target.write_bytes(data)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    expected = PYTHON_SHA256.get(version)
    if verify:
        if not expected:
            raise SystemExit(f"Brak zapisanej sumy SHA-256 dla Pythona {version} (sha256={digest}). "
                             f"Dopisz ją do PYTHON_SHA256 albo użyj --no-verify.")
        if digest != expected:
            target.unlink()
            raise SystemExit(f"Zła suma SHA-256 pakietu Pythona {version}: {digest} (oczekiwano {expected})")
    log(f"Python {version}: sha256 {digest}")
    return target


def extract_python(nupkg: Path, dest: Path) -> None:
    with zipfile.ZipFile(nupkg) as z:
        for info in z.infolist():
            name = info.filename
            if not name.startswith("tools/") or info.is_dir():
                continue
            rel = name[len("tools/"):]
            if rel.startswith(PY_EXCLUDE_PREFIXES) or "/__pycache__/" in rel:
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)


def install_requirements(site_packages: Path, py_version: str) -> None:
    major_minor = ".".join(py_version.split(".")[:2])
    cmd = [sys.executable, "-m", "pip", "install", "--target", str(site_packages),
           "--platform", "win_amd64", "--python-version", major_minor, "--implementation", "cp",
           "--only-binary=:all:", "--no-compile", "--disable-pip-version-check", "--no-warn-script-location",
           "--upgrade", "-r", str(ROOT / "requirements.txt")]
    log("pip: " + " ".join(cmd[3:]))
    subprocess.run(cmd, check=True)
    for junk in site_packages.glob("bin"):
        shutil.rmtree(junk, ignore_errors=True)


def copy_app(dest: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.db", "*.log")
    for item in APP_ITEMS:
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(src, dest / item, ignore=ignore)
        elif src.exists():
            shutil.copy2(src, dest / item)


def write_text_crlf(path: Path, text: str) -> None:
    path.write_bytes(("\ufeff" + text).replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))


def precompile(paths: list[Path], py_version: str) -> None:
    target = tuple(int(x) for x in py_version.split(".")[:2])
    if sys.version_info[:2] != target:
        log(f"pomijam prekompilację (lokalny Python {sys.version_info[0]}.{sys.version_info[1]} ≠ {py_version})")
        return
    import py_compile

    for path in paths:
        compileall.compile_dir(str(path), quiet=1, workers=0,
                               invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
    log("prekompilacja .pyc: gotowe")


def find_makensis() -> str:
    found = shutil.which("makensis")
    if found:
        return found
    for candidate in (r"C:\Program Files (x86)\NSIS\makensis.exe", r"C:\Program Files\NSIS\makensis.exe"):
        if Path(candidate).exists():
            return candidate
    raise SystemExit("Nie znaleziono makensis (NSIS 3). Linux: sudo apt install nsis · Windows: winget install NSIS.NSIS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--python", default=PYTHON_VERSION, help="wersja Pythona z NuGet (domyślnie %(default)s)")
    parser.add_argument("--no-verify", action="store_true", help="nie sprawdzaj sumy SHA-256 pakietu Pythona")
    parser.add_argument("--out", default=str(ROOT / "dist"), help="katalog wynikowy")
    parser.add_argument("--build-dir", default=str(ROOT / "build" / "windows"))
    parser.add_argument("--stage-only", action="store_true", help="tylko przygotuj pliki (bez makensis)")
    args = parser.parse_args()

    build = Path(args.build_dir)
    stage = build / "MatrixFinance"
    out_dir = Path(args.out)
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "python").mkdir(parents=True)
    (stage / "app").mkdir()
    out_dir.mkdir(parents=True, exist_ok=True)

    nupkg = download_python(args.python, build / "cache", verify=not args.no_verify)
    log("rozpakowanie Pythona")
    extract_python(nupkg, stage / "python")
    site_packages = stage / "python" / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    install_requirements(site_packages, args.python)
    log("kopiowanie programu")
    copy_app(stage / "app")
    shutil.copy2(HERE / "MatrixFinance.pyw", stage / "MatrixFinance.pyw")
    shutil.copy2(HERE / "MatrixFinance.ico", stage / "MatrixFinance.ico")
    write_text_crlf(stage / "INSTRUKCJA.txt", (HERE / "INSTRUKCJA.txt").read_text(encoding="utf-8")
                    .replace("{VERSION}", APP_VERSION).replace("{PYVER}", args.python))
    precompile([stage / "app", site_packages], args.python)

    py_dll = f"python{''.join(args.python.split('.')[:2])}.dll"
    if not (stage / "python" / py_dll).exists():
        raise SystemExit(f"Brak {py_dll} w pakiecie Pythona")
    size_mb = sum(f.stat().st_size for f in stage.rglob("*") if f.is_file()) / 1e6
    log(f"pliki programu: {size_mb:.1f} MB")
    if args.stage_only:
        log(f"gotowe (bez instalatora): {stage}")
        return 0

    setup = out_dir / f"MatrixFinance-Setup-{APP_VERSION}.exe"
    nums = [int(x) for x in APP_VERSION.split(".")] + [0, 0, 0]
    cmd = [find_makensis(), "-V2", "-INPUTCHARSET", "UTF8",
           f"-DVERSION={APP_VERSION}", f"-DVIVERSION={'.'.join(map(str, nums[:4]))}",
           f"-DSRCDIR={stage}", f"-DOUTFILE={setup}", f"-DPYVER={args.python}", f"-DPYDLL={py_dll}",
           str(HERE / "MatrixFinance.nsi")]
    log("makensis …")
    subprocess.run(cmd, check=True)
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    (out_dir / f"{setup.name}.sha256").write_text(f"{digest}  {setup.name}\n", encoding="ascii")
    log(f"GOTOWE: {setup} ({setup.stat().st_size / 1e6:.1f} MB) sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
