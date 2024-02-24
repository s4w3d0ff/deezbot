@echo off
set PYTHON_VERSION=3.11
set SPACY_MODEL=en_core_web_sm

rem Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed. Please install Python %PYTHON_VERSION% or later.
    exit /b 1
)

rem Check Python version
python -c "import sys; exit(sys.version_info < (3, 11))"
if %errorlevel% neq 0 (
    echo Python version is less than %PYTHON_VERSION%. Please install Python %PYTHON_VERSION% or later.
    exit /b 1
)

rem Check if pip is installed
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Pip is not installed. Please install pip.
    exit /b 1
)

rem Install Python libraries from requirements.txt
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Failed to install Python libraries. Check requirements.txt and try again.
    exit /b 1
)

rem Check if spaCy model is already downloaded
python -c "import spacy; spacy.load('%SPACY_MODEL%')" >nul 2>&1
if %errorlevel% equ 0 (
    echo SpaCy model '%SPACY_MODEL%' is already downloaded.
) else (
    rem Run Python command to download spaCy model
    python -m spacy download %SPACY_MODEL%
    if %errorlevel% neq 0 (
        echo Failed to download SpaCy model. Check your internet connection and try again.
        exit /b 1
    )
    echo SpaCy model '%SPACY_MODEL%' downloaded successfully.
)

echo Installation completed successfully.
pause
exit /b 0
