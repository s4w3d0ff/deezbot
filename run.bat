@echo off
echo Activating virtual environment...
call deez_venv\Scripts\activate

echo Setting environment variables...
set DEEZ_CLIENT_ID=
set DEEZ_CLIENT_SECRET=

echo Running deez_nuts.py...
python deez_nutz.py

echo Deactivating virtual environment...
call deez_venv\Scripts\deactivate

pause