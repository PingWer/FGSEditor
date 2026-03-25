@echo off
echo Building FGSEditor Executable with PyInstaller...
echo.
echo Please wait...

if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

.venv\Scripts\pyinstaller --noconfirm --noconsole --onefile --icon="icon.ico" --add-data "icon.ico;." --name "FGSEditor" --paths="%cd%" fgseditor_qt\fgsview_loader.py

echo.
echo ==============================================
echo Build completed successfully! 
echo You can find your executable inside:
echo %cd%\dist\FGSEditor
echo ==============================================
pause
