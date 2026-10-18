; Kriko's installer hooks. Tauri's NSIS template calls these macros.
;
; What an installer owes this app:
;
; * Nothing of ours may be running while files are replaced or removed. The
;   engine maps its own image, so a live one fails the copy. The app goes first
;   and the engine second: ending kriko.exe closes the engine's stdin, which is
;   its designed way out, and the second kill is the belt. OpenSERP is a shipped
;   program too, and an orphan of it holds its file against the next install.
;   All three are tree kills (/T) because the frozen engine starts a second
;   process, and the one that holds the file is the child. "No such process" is
;   the normal answer, so none of these can fail the install.
; * A per-user install touches nothing of the machine: no PATH entry, nothing
;   under Program Files (installMode "currentUser" in tauri.conf.json).
; * "Kriko Console" is the operator console as something you double-click: the
;   engine program with its tui flag, wearing the app's icon. A console window
;   appears on purpose, because the terminal is the interface there.

!macro KrikoStopEverything
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM kriko.exe'
  Pop $0
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM kriko-sidecar.exe'
  Pop $0
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM OpenSERP.exe'
  Pop $0
  Sleep 500
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro KrikoStopEverything
!macroend

!macro NSIS_HOOK_POSTINSTALL
  CreateShortcut "$SMPROGRAMS\Kriko Console.lnk" "$INSTDIR\kriko-sidecar.exe" "--tui" "$INSTDIR\kriko.exe" 0
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro KrikoStopEverything
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$SMPROGRAMS\Kriko Console.lnk"
!macroend
