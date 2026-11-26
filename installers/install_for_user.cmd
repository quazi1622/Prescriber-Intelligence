@echo off
setlocal EnableExtensions
set "SOURCE=%~dp0"
set "DEST=%LOCALAPPDATA%\Programs\PrescriberIntelligence"
if not exist "%SOURCE%Prescriber_Intelligence.exe" (
  echo Prescriber_Intelligence.exe is missing from the extracted build folder.
  pause
  exit /b 1
)
if /I "%SOURCE:~0,-1%"=="%DEST%" (
  echo Already installed for this Windows user.
) else (
  if not exist "%DEST%" mkdir "%DEST%"
  xcopy "%SOURCE%*" "%DEST%\" /E /I /Y /Q >nul
  if errorlevel 1 (
    echo Unable to copy files to the current user's application folder.
    pause
    exit /b 1
  )
)
set "LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Prescriber Intelligence.lnk"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK);$s.TargetPath=$env:DEST+'\Prescriber_Intelligence.exe';$s.WorkingDirectory=$env:DEST;$s.Save()"
echo.
echo Installed for current user without administrator permissions.
echo Application: "%DEST%\Prescriber_Intelligence.exe"
echo Prescription database: "%LOCALAPPDATA%\PrescriberIntelligence\data"
echo First-time registration requires an internet connection and administrator approval.
echo.
pause
