@echo off
echo Building FGSEditor Executable with PyInstaller...
echo.
echo Please wait...

if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

.venv\Scripts\pyinstaller --noconfirm --noconsole --onefile --icon="icon.ico" --add-data "icon.ico;." --name "FGSEditor" --paths="%cd%" fgseditor_qt\fgsview_loader.py

echo.
echo Copying FGS_size_table next to the executable...
if exist "dist\FGS_size_table" rmdir /s /q dist\FGS_size_table
xcopy /s /e /i /q FGS_size_table dist\FGS_size_table

echo.
echo ==============================================
echo Build completed successfully! 
echo You can find your executable inside:
echo %cd%\dist\
echo Make sure to distribute FGS_size_table alongside FGSEditor executable
echo ==============================================
pause
