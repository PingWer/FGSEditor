@echo off
echo Building FGSEditor Executable with PyInstaller...
echo.
echo Please wait...

if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

.venv\Scripts\pyinstaller --noconfirm --noconsole --onefile --icon="images\icon.ico" --add-data "images;images" --hidden-import="fgseditor_qt.core" --hidden-import="fgseditor_qt.math" --hidden-import="fgseditor_qt.tools" --hidden-import="fgseditor_qt.ui" --hidden-import="fgseditor_qt.ui.panels" --hidden-import="fgseditor_qt.panels" --name "FGSEditor" --paths="%cd%" fgseditor_qt\fgsview_loader.py

echo.
echo Copying images, FGS_grain_size and Templates next to the executable...
if exist "dist\images" rmdir /s /q dist\images
xcopy /s /e /i /q images dist\images

if exist "dist\FGS_grain_size" rmdir /s /q dist\FGS_grain_size
xcopy /s /e /i /q FGS_grain_size dist\FGS_grain_size

if exist "dist\Templates" rmdir /s /q dist\Templates
xcopy /s /e /i /q Templates dist\Templates

echo Copying external executables (grav1synth.exe, regrain.exe, av-denoise.exe)...
if exist "grav1synth.exe" copy /y grav1synth.exe dist\grav1synth.exe
if exist "regrain.exe" copy /y regrain.exe dist\regrain.exe
if exist "av-denoise.exe" copy /y av-denoise.exe dist\av-denoise.exe

echo Copying NOTICE.md...
if exist "NOTICE.md" copy /y NOTICE.md dist\NOTICE.md

echo Copying settings.json...
if exist "settings.json" copy /y settings.json dist\settings.json

echo.
echo ==============================================
echo Build completed successfully! 
echo You can find your executable inside:
echo %cd%\dist\
echo Make sure to distribute FGS_grain_size, Templates, grav1synth, regrain, and av-denoise alongside FGSEditor.exe
echo ==============================================
pause
