# NB this file is automatically replaced by the make-release script;
# changes made here will not be released.

import subprocess

try:
    version = subprocess.check_output(['git','describe','--dirty']).strip()
except:
    version = ("unknown (not released, and either not in revision control or "
               "the current working directory is not in the quicktill tree)")
