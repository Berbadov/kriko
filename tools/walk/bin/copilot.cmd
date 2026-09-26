@echo off
rem Windows resolves "copilot" through PATHEXT, so it finds copilot.exe/.cmd and never
rem this directory's bare bash script: the real CLI answered the walk. This
rem shim is what PATHEXT finds first here. See tools/walk.sh.
if not defined KRIKO_WALK_BASH set "KRIKO_WALK_BASH=bash"
"%KRIKO_WALK_BASH%" "%~dp0copilot" %*
