"""
Uruchamiacz Matrix Finance dla Windows (skrót na pulpicie i w menu Start).

Uruchamiany przez pythonw.exe (bez migającego okna konsoli). Otwiera program
w Windows Terminal (najlepszy wygląd), a gdy go nie ma — w zwykłym oknie konsoli.
Opcje:  --console  wymuś zwykłą konsolę
        --selftest uruchom test instalacji (okno zostaje otwarte z wynikiem)
        --dry-run  tylko wypisz polecenie (diagnostyka)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON = HERE / "python" / "python.exe"
MAIN = HERE / "app" / "main.py"
TITLE = "Matrix Finance"
CREATE_NEW_CONSOLE = 0x00000010


def find_windows_terminal() -> str | None:
    found = shutil.which("wt.exe") or shutil.which("wt")
    if found:
        return found
    alias = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "wt.exe"
    return str(alias) if alias.exists() else None


def build_command(args: list[str]) -> tuple[list[str], bool]:
    """(polecenie, czy_w_windows_terminal)"""
    if "--selftest" in args:
        # test instalacji: zwykła konsola, okno czeka na Enter, żeby było widać wynik
        return [str(PYTHON), str(MAIN), "--selftest", "--pause"], False
    program = [str(PYTHON), str(MAIN)]
    wt = None if ("--console" in args or os.environ.get("MATRIX_FINANCE_NO_WT") == "1") else find_windows_terminal()
    if wt:
        return [wt, "--title", TITLE, *program], True
    return program, False


def main() -> int:
    args = sys.argv[1:]
    command, in_wt = build_command(args)
    if "--dry-run" in args:
        print(("WT: " if in_wt else "KONSOLA: ") + subprocess.list2cmdline(command))
        return 0
    env = dict(os.environ, MATRIX_FINANCE_PAUSE_ON_ERROR="1", PYTHONUTF8="1")
    try:
        subprocess.Popen(command, cwd=str(HERE / "app"), env=env, creationflags=CREATE_NEW_CONSOLE)
        return 0
    except OSError:
        if in_wt:  # Windows Terminal niedostępny mimo wykrycia — zwykła konsola
            subprocess.Popen([str(PYTHON), str(MAIN)], cwd=str(HERE / "app"), env=env,
                             creationflags=CREATE_NEW_CONSOLE)
            return 0
        raise


if __name__ == "__main__":
    raise SystemExit(main())
