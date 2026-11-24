; =============================================================================
; Matrix Finance — instalator Windows (NSIS 3, Unicode)
;
; Instaluje program razem z własnym Pythonem (nic nie trzeba doinstalowywać),
; bez uprawnień administratora, do %LOCALAPPDATA%\Programs\MatrixFinance.
; Tworzy skrót na pulpicie i w menu Start oraz wpis w „Aplikacje i funkcje”.
; Dane użytkownika (%USERPROFILE%\.matrix_finance) nie są ruszane.
;
; Budowanie: python installer/windows/build_installer.py   (wywołuje makensis)
; Instalacja cicha: MatrixFinance-Setup-X.Y.Z.exe /S   (opcjonalnie /D=C:\ścieżka)
; =============================================================================

Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 32

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "WinVer.nsh"
!include "x64.nsh"

!ifndef VERSION
  !error "Brak -DVERSION=x.y.z"
!endif
!ifndef SRCDIR
  !error "Brak -DSRCDIR=katalog_z_plikami"
!endif
!ifndef OUTFILE
  !define OUTFILE "MatrixFinance-Setup-${VERSION}.exe"
!endif
!ifndef PYVER
  !define PYVER "3"
!endif
!ifndef PYDLL
  !define PYDLL "python3.dll"
!endif
!ifndef VIVERSION
  !define VIVERSION "${VERSION}.0"
!endif

!define APPNAME "Matrix Finance"
!define APPID "MatrixFinance"
!define PUBLISHER "Matrix Finance"
!define HOMEPAGE "https://github.com/ArturKnopek/Matrix-Finance-TUI"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}"
!define UNINST_EXE "Odinstaluj.exe"
!define DATA_DIR "$PROFILE\.matrix_finance"

Name "${APPNAME} ${VERSION}"
Caption "${APPNAME} ${VERSION} — instalacja"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APPID}"
InstallDirRegKey HKCU "${UNINST_KEY}" "InstallLocation"
RequestExecutionLevel user
ShowInstDetails show
ShowUninstDetails show
BrandingText "${APPNAME} ${VERSION}"

VIProductVersion "${VIVERSION}"
VIAddVersionKey /LANG=0 "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=0 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=0 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=0 "FileDescription" "${APPNAME} — instalator"
VIAddVersionKey /LANG=0 "CompanyName" "${PUBLISHER}"
VIAddVersionKey /LANG=0 "LegalCopyright" "Licencja MIT"

; ------------------------------------------------------------------ wygląd

!define MUI_ICON "${SRCDIR}\MatrixFinance.ico"
!define MUI_UNICON "${SRCDIR}\MatrixFinance.ico"
!define MUI_ABORTWARNING
!define MUI_COMPONENTSPAGE_SMALLDESC

!define MUI_WELCOMEPAGE_TITLE "Witaj w instalatorze ${APPNAME} ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "Matrix Finance to program do prowadzenia budżetu domowego połączonego z oszczędzaniem kopertowym (konta, lokaty, cele, auto-oszczędzanie, raporty).$\r$\n$\r$\nInstalator zawiera wszystko, czego program potrzebuje — także Python ${PYVER} — więc nie trzeba niczego doinstalowywać ani mieć uprawnień administratora.$\r$\n$\r$\nTwoje dane (folder .matrix_finance w katalogu użytkownika) nie są zmieniane podczas instalacji ani aktualizacji.$\r$\n$\r$\nKliknij Dalej, aby kontynuować."

!define MUI_FINISHPAGE_TITLE "Matrix Finance jest gotowy"
!define MUI_FINISHPAGE_TEXT "Program uruchomisz skrótem „Matrix Finance” na pulpicie lub w menu Start.$\r$\n$\r$\nNajlepiej wygląda w Windows Terminal (jest w Windows 11; w Windows 10 można go pobrać ze Sklepu Microsoft) — jeśli jest zainstalowany, program otworzy się w nim automatycznie.$\r$\n$\r$\nW programie: F1 — pomoc i skróty klawiszowe."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Uruchom Matrix Finance"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\INSTRUKCJA.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Pokaż instrukcję"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!define MUI_FINISHPAGE_NOREBOOTSUPPORT

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Polish"

; ------------------------------------------------------------------ pomocnicze

; Program uruchomiony = plik DLL Pythona jest zablokowany; prosimy o zamknięcie.
!macro CHECK_NOT_RUNNING UN
Function ${UN}CheckNotRunning
  IfFileExists "$INSTDIR\python\${PYDLL}" 0 done
  retry:
    ClearErrors
    Rename "$INSTDIR\python\${PYDLL}" "$INSTDIR\python\${PYDLL}.mf-check"
    IfErrors 0 free
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Matrix Finance jest uruchomiony.$\r$\n$\r$\nZamknij program (Ctrl+Q) i kliknij Ponów." /SD IDCANCEL IDRETRY retry
      Abort "Przerwano: program jest uruchomiony."
  free:
    Rename "$INSTDIR\python\${PYDLL}.mf-check" "$INSTDIR\python\${PYDLL}"
  done:
FunctionEnd
!macroend
!insertmacro CHECK_NOT_RUNNING ""
!insertmacro CHECK_NOT_RUNNING "un."

Function LaunchApp
  SetOutPath "$INSTDIR\app"
  Exec '"$INSTDIR\python\pythonw.exe" "$INSTDIR\MatrixFinance.pyw"'
FunctionEnd

Function .onInit
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "Matrix Finance wymaga Windows 10 lub nowszego." /SD IDOK
    Abort
  ${EndIf}
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "Matrix Finance wymaga 64-bitowego systemu Windows." /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

; ------------------------------------------------------------------ instalacja

Section "Matrix Finance (wymagane)" SecMain
  SectionIn RO
  Call CheckNotRunning

  ; aktualizacja: usuń poprzednie pliki programu (dane użytkownika są gdzie indziej)
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\python"

  SetOutPath "$INSTDIR"
  File /r "${SRCDIR}\*.*"
  CreateDirectory "${DATA_DIR}"

  WriteUninstaller "$INSTDIR\${UNINST_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\MatrixFinance.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\${UNINST_EXE}"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\${UNINST_EXE}" /S'
  WriteRegStr HKCU "${UNINST_KEY}" "URLInfoAbout" "${HOMEPAGE}"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "Skrót na pulpicie" SecDesktop
  SetOutPath "$INSTDIR\app"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\MatrixFinance.pyw"' \
    "$INSTDIR\MatrixFinance.ico" 0 SW_SHOWNORMAL "" "Budżet domowy i oszczędzanie kopertowe"
SectionEnd

Section "Skróty w menu Start" SecStartMenu
  SetOutPath "$INSTDIR\app"
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\MatrixFinance.pyw"' \
    "$INSTDIR\MatrixFinance.ico" 0 SW_SHOWNORMAL "" "Budżet domowy i oszczędzanie kopertowe"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Sprawdź instalację.lnk" "$INSTDIR\python\pythonw.exe" \
    '"$INSTDIR\MatrixFinance.pyw" --selftest' "$INSTDIR\MatrixFinance.ico" 0 SW_SHOWNORMAL "" \
    "Test działania programu na danych tymczasowych"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Folder z danymi.lnk" "${DATA_DIR}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Instrukcja.lnk" "$INSTDIR\INSTRUKCJA.txt"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Odinstaluj ${APPNAME}.lnk" "$INSTDIR\${UNINST_EXE}"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "Program i wbudowany Python ${PYVER} (bez zmian w systemie)."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "Ikona „Matrix Finance” na pulpicie."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} "Program, test instalacji, folder z danymi i deinstalator w menu Start."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ------------------------------------------------------------------ deinstalacja

Function un.onInit
  ; deinstalator działa w katalogu programu (InstallLocation z rejestru)
FunctionEnd

Section "Uninstall"
  Call un.CheckNotRunning
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"

  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\python"
  Delete "$INSTDIR\MatrixFinance.pyw"
  Delete "$INSTDIR\MatrixFinance.ico"
  Delete "$INSTDIR\INSTRUKCJA.txt"
  Delete "$INSTDIR\${UNINST_EXE}"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"

  ; dane finansowe zostają, chyba że użytkownik wyraźnie zdecyduje inaczej (w trybie cichym: zostają)
  IfFileExists "${DATA_DIR}\*.*" 0 done
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "Usunąć także Twoje dane finansowe?$\r$\n$\r$\n${DATA_DIR}$\r$\n$\r$\nUWAGA: tego nie da się cofnąć. Wybierz NIE, jeśli zamierzasz zainstalować program ponownie (dane zostaną)." /SD IDNO IDNO done
    RMDir /r "${DATA_DIR}"
  done:
SectionEnd
