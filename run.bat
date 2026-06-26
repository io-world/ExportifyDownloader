@echo off
setlocal enableextensions

:: ---- Config ----
set "SCRIPT_DIR=%~dp0"
set "LOG_FILE=%SCRIPT_DIR%run_log.txt"
set "PYTHON_SCRIPT=%SCRIPT_DIR%main.py"
set "VENV_ACTIVATE=%SCRIPT_DIR%.venv\Scripts\activate.bat"

:: ---- Timestamp helper ----
for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set "D=%%a-%%b-%%c"
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set "T=%%a:%%b"

echo. >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"
echo Started: %D% %T% >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"

:: ---- Change to script directory ----
cd /d "%SCRIPT_DIR%"
if errorlevel 1 (
    echo ERROR: Could not change to script directory: %SCRIPT_DIR% >> "%LOG_FILE%"
    exit /b 1
)

:: ---- Activate virtual environment ----
if not exist "%VENV_ACTIVATE%" (
    echo ERROR: Virtual environment not found at %VENV_ACTIVATE% >> "%LOG_FILE%"
    exit /b 1
)
call "%VENV_ACTIVATE%"
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment. >> "%LOG_FILE%"
    exit /b 1
)

:: ---- Run the Python script ----
if not exist "%PYTHON_SCRIPT%" (
    echo ERROR: Python script not found at %PYTHON_SCRIPT% >> "%LOG_FILE%"
    exit /b 1
)

python "%PYTHON_SCRIPT%"
set "EXIT_CODE=%errorlevel%"

:: ---- Log result ----
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set "T=%%a:%%b"
if %EXIT_CODE% equ 0 (
    echo Finished successfully at %T%. >> "%LOG_FILE%"
) else (
    echo ERROR: Script exited with code %EXIT_CODE% at %T%. >> "%LOG_FILE%"
)

exit /b %EXIT_CODE%
