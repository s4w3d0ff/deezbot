@echo off
echo Installing necessary Python packages...
pip install -r requirements.txt

echo Installing spaCy model...
python -m spacy download en_core_web_sm

echo Installation complete!
pause