@echo off
setlocal

REM Build a Windows .exe bundle with embedded Python runtime via PyInstaller.
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\.."
set "APP_SCRIPT=%PROJECT_ROOT%\windows_app\vocal_canvas_windows.py"
set "OUTPUT_DIR=%SCRIPT_DIR%dist"
set "WORK_DIR=%SCRIPT_DIR%build"
set "SPEC_DIR=%SCRIPT_DIR%"
set "PY_CMD=python"

if not exist "%APP_SCRIPT%" (
  echo [ERROR] Missing app script:
  echo   %APP_SCRIPT%
  exit /b 1
)

python --version >nul 2>&1
if errorlevel 1 (
  if exist "C:\users\crossover\AppData\Local\Programs\Python\Python311\python.exe" (
    set "PY_CMD=C:\users\crossover\AppData\Local\Programs\Python\Python311\python.exe"
  )
)

echo [0/3] Using Python command:
echo   %PY_CMD%

echo [1/3] Installing build dependencies...
%PY_CMD% -m ensurepip --upgrade >nul 2>&1
%PY_CMD% -m pip install --upgrade pip
if errorlevel 1 exit /b 1

%PY_CMD% -m pip install -r "%PROJECT_ROOT%\windows_app\requirements.txt" pyinstaller
if errorlevel 1 exit /b 1

echo [2/3] Building VocalCanvasSetup.exe with PyInstaller...
%PY_CMD% -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onefile ^
  --name "VocalCanvasSetup" ^
  --distpath "%OUTPUT_DIR%" ^
  --workpath "%WORK_DIR%" ^
  --specpath "%SPEC_DIR%" ^
  "%APP_SCRIPT%"
if errorlevel 1 exit /b 1

echo [3/3] Done.
echo Output:
echo   %OUTPUT_DIR%\VocalCanvasSetup.exe
echo.
echo Note: This .exe is intentionally not linked on the website yet.
endlocal
