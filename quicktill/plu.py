from __future__ import unicode_literals

from . import pricecheck
import logging
log=logging.getLogger(__name__)

# XXX remove this after all till configurations have been updated
def popup():
    log.warning(
        "Config file needs updating: import popup from pricecheck not plu")
    pricecheck.popup()

def listunbound():
    pass

def plumenu():
    pass
