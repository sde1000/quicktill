from . import pricecheck
import logging
log=logging.getLogger(__name__)

def popup():
    log.warning(
        "Config file needs updating: import popup from pricecheck not plu")
    pricecheck.popup()
