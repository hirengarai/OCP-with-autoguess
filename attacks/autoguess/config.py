# Path to Sagemath executable
# PATH_SAGE = '/usr/local/bin/sage'
# PATH_SAGE = '/usr/bin/sage'
# PATH_SAGE = 'python3'
# TEMP_DIR = 'temp'

# attacks/autoguess/config.py

from pathlib import Path

# Get the directory where config.py is located
BASE_DIR = Path(__file__).resolve().parent

TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

PATH_SAGE = "python3"  # or your sage path if needed