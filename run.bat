@echo off
setlocal enableextensions

:: ---- Config ----
set "SCRIPT_DIR=%~dp0"
set "LOG_DIR=%SCRIPT_DIR%run_logs"
set "PYTHON_SCRIPT=%SCRIPT_DIR%main.py"
set "VENV_ACTIVATE=%SCRIPT_DIR%.venv\Scripts\activate.bat"

:: ---- Timestamp helper ----
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_TS=%%I"
for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-Date -Format \"yyyy-MM-dd HH:mm:ss\""') do set "RUN_HUMAN=%%I"
set "LOG_FILE=%LOG_DIR%\run_%RUN_TS%.txt"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if errorlevel 1 (
    echo ERROR: Could not create log directory: %LOG_DIR%
    exit /b 1
)

powershell -NoProfile -Command "$utf8NoBom = New-Object System.Text.UTF8Encoding($false); [System.IO.File]::WriteAllText('%LOG_FILE%', \"============================================================`r`nStarted: %RUN_HUMAN%`r`n============================================================`r`n`r`n\", $utf8NoBom)"

echo Logging this run to: "%LOG_FILE%"

:: ---- Change to script directory ----
cd /d "%SCRIPT_DIR%"
if errorlevel 1 (
    echo ERROR: Could not change to script directory: %SCRIPT_DIR%
    powershell -NoProfile -Command "Add-Content -Path '%LOG_FILE%' -Value 'ERROR: Could not change to script directory: %SCRIPT_DIR%' -Encoding utf8"
    exit /b 1
)

:: ---- Activate virtual environment ----
if not exist "%VENV_ACTIVATE%" (
    echo ERROR: Virtual environment not found at %VENV_ACTIVATE%
    powershell -NoProfile -Command "Add-Content -Path '%LOG_FILE%' -Value 'ERROR: Virtual environment not found at %VENV_ACTIVATE%' -Encoding utf8"
    exit /b 1
)
call "%VENV_ACTIVATE%"
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment.
    powershell -NoProfile -Command "Add-Content -Path '%LOG_FILE%' -Value 'ERROR: Failed to activate virtual environment.' -Encoding utf8"
    exit /b 1
)

:: ---- Run the Python script ----
if not exist "%PYTHON_SCRIPT%" (
    echo ERROR: Python script not found at %PYTHON_SCRIPT%
    powershell -NoProfile -Command "Add-Content -Path '%LOG_FILE%' -Value 'ERROR: Python script not found at %PYTHON_SCRIPT%' -Encoding utf8"
    exit /b 1
)

echo Running downloader...
powershell -NoProfile -Command "Add-Content -Path '%LOG_FILE%' -Value 'Running downloader...' -Encoding utf8"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$exitCode = 0; $env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; try { & python '%PYTHON_SCRIPT%' 2>&1 | ForEach-Object { $_; Add-Content -Path '%LOG_FILE%' -Value $_ -Encoding utf8 } } finally { $exitCode = $LASTEXITCODE; if ($null -eq $exitCode) { $exitCode = 0 }; exit $exitCode }"
set "EXIT_CODE=%errorlevel%"

:: ---- Log result ----
for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-Date -Format \"yyyy-MM-dd HH:mm:ss\""') do set "END_HUMAN=%%I"
if %EXIT_CODE% equ 0 (
    echo.
    echo Finished successfully at %END_HUMAN%.
    powershell -NoProfile -Command "Add-Content -Path '%LOG_FILE%' -Value '' -Encoding utf8"
    powershell -NoProfile -Command "Add-Content -Path '%LOG_FILE%' -Value 'Finished successfully at %END_HUMAN%.' -Encoding utf8"
) else (
    echo.
    echo ERROR: Script exited with code %EXIT_CODE% at %END_HUMAN%.
    powershell -NoProfile -Command "Add-Content -Path '%LOG_FILE%' -Value '' -Encoding utf8"
    powershell -NoProfile -Command "Add-Content -Path '%LOG_FILE%' -Value 'ERROR: Script exited with code %EXIT_CODE% at %END_HUMAN%.' -Encoding utf8"
)

exit /b %EXIT_CODE%
