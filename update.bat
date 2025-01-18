@echo off

echo Activating virtual environment...
call deez_venv\Scripts\activate

echo Updating pip...
python -m pip install --upgrade pip

echo Updating Python packages...
pip install --upgrade -r requirements.txt

echo Deactivating virtual environment...
call deez_venv\Scripts\deactivate

echo Update complete!
pause