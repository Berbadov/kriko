; Windows installer hooks.
;
; One job: nothing of ours may be running when the installer starts writing.
; Tauri's own NSIS template already handles Kriko.exe — it detects the running
; app and closes it — but it knows nothing about the sidecar, and the sidecar is
; the process that breaks the install. It is a PyInstaller onefile binary, so it
; keeps its own image mapped while it lives, and NSIS then stops with
;
;     Error opening file for writing:
;     C:\Users\<you>\AppData\Local\Kriko\kriko-sidecar.exe
;
; whose Abort/Retry/Ignore are all wrong answers: Ignore leaves the old engine
; in place beside a new shell.
;
; The engine also ends itself now when the shell's stdin closes (see
; --exit-with-parent in src/app/sidecar.py). This hook is the belt for the case
; that watchdog cannot cover: a machine where one already leaked, before this
; version was installed.

!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping any running Kriko engine…"
  ; /T for the tree, because onefile means the pid holding the file is a child.
  ; Errors are ignored on purpose: "not found" is the expected outcome.
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM kriko-sidecar.exe'
  Pop $0
  Sleep 500
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  DetailPrint "Stopping any running Kriko engine…"
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM kriko-sidecar.exe'
  Pop $0
  Sleep 500
!macroend
