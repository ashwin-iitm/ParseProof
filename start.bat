@echo off
rem AdoVerse - sets itself up on first run, then starts the server and opens the app in your browser.
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo Setting up Python packages. This happens once and takes a few minutes...
  python -m venv venv || (echo Python 3.11 or newer is needed: https://www.python.org/downloads/ & pause & exit /b 1)
  venv\Scripts\python.exe -m pip install --upgrade pip
  venv\Scripts\python.exe -m pip install -r requirements.txt || (pause & exit /b 1)
)

if not exist "web\dist\index.html" (
  echo Building the web app. This happens once...
  where npm >nul 2>nul || (echo Node.js 18 or newer is needed: https://nodejs.org/ & pause & exit /b 1)
  pushd web
  call npm install --no-audit --no-fund
  call npm run build
  popd
)

if not exist ".env" copy ".env.example" ".env" >nul

start "" http://127.0.0.1:8010
venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8010
