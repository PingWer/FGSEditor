@echo off
echo Building FGSEditor Executable with PyInstaller...
echo.
echo Please wait...

if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

.venv\Scripts\pyinstaller --noconfirm --noconsole --onefile --icon="icon.ico" --add-data "icon.ico;." --hidden-import="fgseditor_qt.panels" --name "FGSEditor" --paths="%cd%" fgseditor_qt\fgsview_loader.py

echo.
echo Copying FGS_grain_size and Templates next to the executable...
if exist "dist\FGS_grain_size" rmdir /s /q dist\FGS_grain_size
xcopy /s /e /i /q FGS_grain_size dist\FGS_grain_size

if exist "dist\Templates" rmdir /s /q dist\Templates
xcopy /s /e /i /q Templates dist\Templates

echo Copying NOTICE.md...
if exist "NOTICE.md" copy /y NOTICE.md dist\NOTICE.md

echo.
echo ==============================================
echo Build completed successfully! 
echo You can find your executable inside:
echo %cd%\dist\
echo Make sure to distribute FGS_grain_size, Templates, and grav1synth alongside FGSEditor.exe
echo ==============================================
pause
