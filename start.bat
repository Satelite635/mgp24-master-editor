@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH" in the installer.
  pause
  exit /b 1
)
python -c "import Crypto" >nul 2>nul
if errorlevel 1 (
  echo Installing pycryptodome ^(one time^)...
  python -m pip install pycryptodome
  if errorlevel 1 ( echo Install failed. & pause & exit /b 1 )
)
python -c "import blake3" >nul 2>nul
if errorlevel 1 (
  echo Installing blake3 ^(one time, makes MotoGP 25 packing fast^)...
  python -m pip install blake3
  if errorlevel 1 echo blake3 install failed - packing still works, just slower.
)
python -c "import zstandard" >nul 2>nul
if errorlevel 1 (
  echo Installing zstandard ^(one time, reads compressed .usmap files for "Copy values from..."^)...
  python -m pip install zstandard
  if errorlevel 1 echo zstandard install failed - "Copy values from..." then needs an uncompressed .usmap for MotoGP 25.
)
python motogp_master_editor.py web
pause
