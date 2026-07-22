#!/usr/bin/env bash
set -e  # stop on first error

echo "Creating virtual environment..."
python3 -m venv deez_venv

echo "Activating virtual environment..."
source deez_venv/bin/activate

echo "Updating pip..."
python -m pip install --upgrade pip

echo "Installing necessary Python packages..."
pip install --upgrade -r requirements.txt

echo "Installing spaCy model..."
python -m spacy download en_core_web_sm

echo "Deactivating virtual environment..."
deactivate

echo "Installation complete!"
