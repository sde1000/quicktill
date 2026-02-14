# NB this file is automatically replaced by the make-release script;
# changes made here will not be released.

import subprocess
from pathlib import Path

try:
    here = Path(__file__).resolve().parent
    version = subprocess.check_output(
        ['git', 'describe', '--dirty', '--always'],
        cwd=here).strip().decode('utf-8')
    shortversion = version
except Exception:
    version = ("unknown (not released, and either not in revision control or "
               "the current working directory is not in the quicktill tree)")
    shortversion = "unknown"
