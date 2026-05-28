@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv" (
    py -3 -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

start "" "http://localhost:8501"
streamlit run app.py --server.address localhost --server.port 8501

pause

