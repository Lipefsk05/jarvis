#!/usr/bin/env bash
# Copies the tray app to the Windows side (so it can start at login, before WSL is up)
# and, with --autostart, adds a shortcut to the Windows Startup folder.
# Usage: tray/install.sh [--autostart | --no-autostart | --desktop-shortcut]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIN_USER="$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r')"
DEST="/mnt/c/Users/${WIN_USER}/AppData/Local/Jarvis"
PYTHONW="C:\\Users\\${WIN_USER}\\AppData\\Local\\Programs\\Python\\Python312\\pythonw.exe"
SCRIPT_WIN="C:\\Users\\${WIN_USER}\\AppData\\Local\\Jarvis\\jarvis_tray.py"

mkdir -p "$DEST"
cp "$HERE/jarvis_tray.py" "$DEST/jarvis_tray.py"
echo "Copiado para $DEST"

case "${1:-}" in
  --autostart)
    powershell.exe -NoProfile -Command "
      \$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Jarvis.lnk'
      \$s = (New-Object -ComObject WScript.Shell).CreateShortcut(\$lnk)
      \$s.TargetPath = '$PYTHONW'
      \$s.Arguments = '\"$SCRIPT_WIN\"'
      \$s.WorkingDirectory = 'C:\\Users\\${WIN_USER}\\AppData\\Local\\Jarvis'
      \$s.Save()"
    echo "Atalho de inicialização criado (Jarvis.lnk)."
    ;;
  --desktop-shortcut)
    # Click to bring the tray back if it ever disappears; a second click is harmless (the tray holds a lock).
    powershell.exe -NoProfile -Command "
      \$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Jarvis.lnk'
      \$s = (New-Object -ComObject WScript.Shell).CreateShortcut(\$lnk)
      \$s.TargetPath = '$PYTHONW'
      \$s.Arguments = '\"$SCRIPT_WIN\"'
      \$s.WorkingDirectory = 'C:\\Users\\${WIN_USER}\\AppData\\Local\\Jarvis'
      \$s.Save()"
    echo "Atalho criado na área de trabalho (Jarvis.lnk)."
    ;;
  --no-autostart)
    powershell.exe -NoProfile -Command "Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'Jarvis.lnk') -ErrorAction SilentlyContinue"
    echo "Atalho de inicialização removido."
    ;;
esac
