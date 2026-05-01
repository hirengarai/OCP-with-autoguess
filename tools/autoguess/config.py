"""
Runtime configuration for autoguess-without-sage.

Importing this module has side effects: if a MiniZinc binary is found,
its containing directory is prepended to ``os.environ["PATH"]`` so the
``minizinc`` Python package's __init__ does not emit a "MiniZinc was not
found" warning.
"""

import os
import platform
import shutil

# Autoguess home directory (for MiniZinc downloads, temp files, etc.)
AUTOGUESS_HOME = os.path.join(os.path.expanduser("~"), ".autoguess")

TEMP_DIR = "temp"


def find_minizinc_path():
    """
    Locate the MiniZinc binary.

    Search order:
    1. MINIZINC_PATH environment variable
    2. ~/.autoguess/minizinc/ (our runtime downloader location)
    3. System PATH (via ``shutil.which``)
    """
    env_path = os.environ.get("MINIZINC_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    managed_dir = os.path.join(AUTOGUESS_HOME, "minizinc")
    system = platform.system()
    if system in ("Darwin", "Linux"):
        managed_bin = os.path.join(managed_dir, "bin", "minizinc")
    else:
        managed_bin = os.path.join(managed_dir, "minizinc.exe")

    if os.path.isfile(managed_bin):
        return managed_bin

    system_bin = shutil.which("minizinc")
    if system_bin:
        return system_bin

    return None


def ensure_minizinc_driver():
    """
    Make sure the ``minizinc`` Python package knows where our MiniZinc binary
    lives.  If ``minizinc.default_driver`` is *None* (i.e. MiniZinc was not
    found on the system PATH), we point it at the binary discovered by
    ``find_minizinc_path()``.

    Call this once before any code that touches ``minizinc.default_driver``.
    """
    try:
        import minizinc
    except ImportError:
        return

    if minizinc.default_driver is not None:
        return

    mzn_path = find_minizinc_path()
    if mzn_path is None:
        return

    from pathlib import Path

    try:
        drv = minizinc.Driver(Path(mzn_path))
        minizinc.default_driver = drv
    except Exception:
        pass


# Eagerly resolve MiniZinc path and prepend its bin directory to PATH
# so that ``import minizinc`` finds it during its __init__ and does not
# emit a "MiniZinc was not found" RuntimeWarning.
MINIZINC_PATH = find_minizinc_path()
if MINIZINC_PATH is not None:
    _mzn_bin_dir = os.path.dirname(MINIZINC_PATH)
    if _mzn_bin_dir not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = _mzn_bin_dir + os.pathsep + os.environ.get("PATH", "")
    # Bundled solver binaries (e.g. fzn-cp-sat / OR-Tools) link against
    # shared libraries shipped inside the MiniZinc bundle's lib/ directory.
    # We do NOT set LD_LIBRARY_PATH globally here because it would pollute
    # the environment for other subprocesses (e.g. Graphviz's dot).  Instead
    # we export the path so gdcp.py can set it only around the solve() call.
    _mzn_lib_dir = os.path.join(os.path.dirname(_mzn_bin_dir), "lib")
    MINIZINC_LIB_DIR = _mzn_lib_dir if os.path.isdir(_mzn_lib_dir) else None
else:
    MINIZINC_LIB_DIR = None
