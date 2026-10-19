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
; * The engine's folder is replaced whole, never overlaid. An installer only
;   writes the files it carries, so the previous engine's leftovers stayed
;   beside the new one: `kriko-0.2.3.dist-info` survived the update to 0.2.4 and
;   the engine read its version from the old copy ("the 0.2.4 installer shows
;   0.2.3"). The uninstaller removes only what it carries as well, so those
;   leftovers also kept the folder from going away. `_internal` is the one folder
;   that is wholly the engine's own; nothing of the reader's lives in it (their
;   catalogs and chats are in `.kriko` in their profile), so it is cleared with
;   the program stopped, before an install and before an uninstall. The install
;   folder itself is never removed this way.
; * Engines an in-app update staged live in `%LOCALAPPDATA%\Kriko\engines`, one
;   folder each, and belong to the program, so an uninstall removes them too.
;   An install does not: an engine newer than the one this installer carries is
;   the reader's update, and one that is not newer is never chosen and is removed
;   by the engine itself.
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

!macro KrikoClearEngineFolder
  RMDir /r "$INSTDIR\_internal"
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro KrikoStopEverything
  !insertmacro KrikoClearEngineFolder
!macroend

!macro NSIS_HOOK_POSTINSTALL
  CreateShortcut "$SMPROGRAMS\Kriko Console.lnk" "$INSTDIR\kriko-sidecar.exe" "--tui" "$INSTDIR\kriko.exe" 0
!macroend

!macro KrikoClearStagedEngines
  RMDir /r "$LOCALAPPDATA\Kriko\engines"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro KrikoStopEverything
  !insertmacro KrikoClearEngineFolder
  !insertmacro KrikoClearStagedEngines
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$SMPROGRAMS\Kriko Console.lnk"
!macroend
