import logging

from io_config.cli import LOGLEVEL


# --- Low-Level-Loggers ---
logging.getLogger("whisperlivekit.audio_processor").setLevel(logging.WARNING)
logging.getLogger("faster_whisper").setLevel(logging.WARNING)

# --- Own Logger ---
class RelativeSeconds(logging.Formatter):
    def format(self, record):
        record.relativeCreated = record.relativeCreated // 1000
        return super().format(record)

formatter = RelativeSeconds("%(relativeCreated)ds %(levelname)s %(module)s.%(funcName)s:\n%(message)s")
logging.basicConfig()
logging.root.handlers[0].setFormatter(formatter)
LOGGER: logging.Logger = logging.getLogger(__name__)
if LOGLEVEL == 'debug':
    LOGGER.setLevel(logging.DEBUG)
elif LOGLEVEL == 'info':
    LOGGER.setLevel(logging.INFO)
elif LOGLEVEL == 'error':
    LOGGER.setLevel(logging.ERROR)
else:
    LOGGER.setLevel(logging.INFO)