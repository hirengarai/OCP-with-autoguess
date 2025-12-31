from pathlib import Path

# Path to Sagemath executable
# PATH_SAGE = '/usr/local/bin/sage'
# PATH_SAGE = '/usr/bin/sage'
PATH_SAGE = 'python3'
TEMP_DIR = str(Path(__file__).resolve().parents[2] / 'files' / 'autoguess' / 'temp')
