@echo off
echo Creating virtual environment...
python -m venv deez_venv

echo Activating virtual environment...
call deez_venv\Scripts\activate

echo Updating pip...
python -m pip install --upgrade pip

echo Installing necessary Python packages...
pip install --upgrade -r requirements.txt

echo Installing spaCy model...
python -m spacy download en_core_web_sm

echo Deactivating virtual environment...
call deez_venv\Scripts\deactivate

echo Installation complete!
pause