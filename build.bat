@echo off
setlocal
REM 1) Build C# cleanup
cd win_cleanup
dotnet publish -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o ../bin
cd ..

REM 2) Copy exe into scripts
mkdir scripts 2>nul
copy /Y bin\WinCleanup.exe scripts\cleanup.exe

REM 3) Install Python deps
python -m pip install -r requirements.txt

REM 4) PyInstaller build
pyinstaller --noconfirm --onefile --windowed --add-data "scripts;scripts" --add-data "assets;assets" main.py

REM 5) Optionally embed manifest (if you made app.manifest)
REM mt.exe -manifest app.manifest -outputresource:dist\main.exe;#1

echo Build finished. Check dist\ for the single executable.
pause