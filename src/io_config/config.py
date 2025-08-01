from typing import Final

import yaml

from io_config.cli import CONFIG_FILE
from io_config.logger import LOGGER

# get Config from yml file
LOGGER.debug('Loading config file...')
try:
    with open(CONFIG_FILE, 'r') as f:
        CONFIG:dict = yaml.load(f, Loader=yaml.FullLoader)
except FileNotFoundError:
    LOGGER.exception('Config File not Found:', CONFIG_FILE); exit()

# Pretalx-Section
JSON_URL: Final[str] = CONFIG['pretalx']['json_url']
CACHE_TIME: Final[int] = CONFIG['pretalx']['cache_time']

# FastAPI-Section
API_HOST: Final[str] = CONFIG['fastapi']['host']
API_Port: Final[int] = CONFIG['fastapi']['port']

# LibreTranslate-Section
LT_HOST: Final[str] = CONFIG['libretranslate']['host']
LT_PORT: Final[int] = CONFIG['libretranslate']['port']