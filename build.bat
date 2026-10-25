@echo off
setlocal
echo ========================================================
echo        RotGuard - Compilation Executable Windows
echo ========================================================
echo.

where python >nul 2>&1
if %errorlevel% equ 0 (
    python build.py
    goto end
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py build.py
    goto end
)

echo [ERREUR] Python n'a pas ete trouve dans le PATH systeme.
echo Veuillez verifier que Python 3 est installe et accessible.

:end
echo.
pause
