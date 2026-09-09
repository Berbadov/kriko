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
