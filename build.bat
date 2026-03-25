@echo off
echo Building SimMovieMaker with Nuitka...
echo.

REM Activate conda environment if needed
REM call conda activate D:\condaenv\smm

python -m nuitka ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=assets/smm.ico ^
    --include-package=simmovimaker ^
    --include-data-dir=assets=assets ^
    --output-dir=build ^
    --output-filename=SimMovieMaker.exe ^
    --enable-plugin=tk-inter ^
    --company-name="SimMovieMaker" ^
    --product-name="SimMovieMaker" ^
    --product-version=2.0.0 ^
    --file-description="SimMovieMaker - Video Creator" ^
    --copyright="SimMovieMaker Contributors" ^
    main.py

echo.
if %ERRORLEVEL% EQU 0 (
    echo Build successful! Output in build/ directory.
) else (
    echo Build failed with error code %ERRORLEVEL%
)
pause
