; Windows installer hooks.
;
; One job: nothing of ours may be running when the installer starts writing.
; Tauri's own NSIS template already handles Kriko.exe -- it detects the running
; app and closes it -- but it knows nothing about the sidecar, and the sidecar is
; the process that breaks the install. It is a PyInstaller onefile binary, so it
; keeps its own image mapped while it lives, and NSIS then stops with
;
;     Error opening file for writing:
;     C:\Users\<you>\AppData\Local\Kriko\kriko-sidecar.exe
;
; whose Abort/Retry/Ignore are all wrong answers: Ignore leaves the old engine
; in place beside a new shell.
;
; The engine also ends itself when the shell's stdin closes (see
; --exit-with-parent in src/app/sidecar.py).
;
; This hook used to be the belt for one rare case -- a machine where an engine
; had already leaked. It is now the normal path. Since the window's close
; button hides rather than quits (tray mode, see src/main.rs rule 3), a reader
; who "closed" Kriko before running an installer still has a live shell and a
; live sidecar, and the sidecar is the process that breaks the install.
;
; Order matters: the shell first, then the engine. Killing Kriko.exe closes the
; pipe the sidecar watches, so the engine ends itself the way it was designed
; to; killing the engine first would instead make a still-running shell report
; a dead engine to a reader who is watching an installer, which looks like the
; installer broke the app. Tauri's own NSIS template also offers to close
; Kriko.exe, and doing it here as well is deliberate: that prompt can be
; declined, and this must not depend on the answer.

!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping any running Kriko..."
  ; The shell first: its exit closes the sidecar's stdin, which is the engine's
  ; own designed way to end. Errors are ignored on purpose throughout --
  ; "not found" is the expected outcome.
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM Kriko.exe'
  Pop $0
  Sleep 500
  ; Then the engine as the belt. /T for the tree, because onefile means the pid
  ; holding the file is a child of the one we can name.
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM kriko-sidecar.exe'
  Pop $0
  Sleep 500
!macroend

; ── the console, as a thing you double-click ─────────────────────────────
;
; `kriko-sidecar.exe --tui` is the operator console (src/app/tui/). It is the
; same binary Tauri already installs beside Kriko.exe as an externalBin, so this
; ships no second artifact -- it is a shortcut with an argument.
;
; It exists because the console's whole reason for existing is a window that
; would not open, and an entry point of "find a terminal, find the install
; directory, type a flag" is not an answer to that. Start menu, one click, a
; real console window.
;
; A console window does appear, and that is the point rather than an oversight:
; the sidecar is built `console=True` (see packaging/kriko-sidecar.spec, which
; explains why -- windowed mode leaves sys.stdout as None and the port handshake
; would raise). Tauri's shell plugin suppresses it with CREATE_NO_WINDOW when it
; spawns the engine; nothing suppresses it here, because here the terminal *is*
; the UI.
;
; Attaching or starting is the console's own decision: with the app running it
; finds the engine on EXTENSION_PORT and shares its store and jobs; with nothing
; running it starts an engine in-process. Either way one click is the whole
; interaction.
!macro NSIS_HOOK_POSTINSTALL
  DetailPrint "Adding the Kriko Console shortcut..."
  CreateShortcut "$SMPROGRAMS\Kriko Console.lnk" "$INSTDIR\kriko-sidecar.exe" "--tui" "$INSTDIR\Kriko.exe" 0
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$SMPROGRAMS\Kriko Console.lnk"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  DetailPrint "Stopping any running Kriko..."
  ; The shell first: its exit closes the sidecar's stdin, which is the engine's
  ; own designed way to end. Errors are ignored on purpose throughout --
  ; "not found" is the expected outcome.
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM Kriko.exe'
  Pop $0
  Sleep 500
  ; Then the engine as the belt. /T for the tree, because onefile means the pid
  ; holding the file is a child of the one we can name.
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM kriko-sidecar.exe'
  Pop $0
  Sleep 500
!macroend
