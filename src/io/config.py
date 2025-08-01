from typing import Final

import yaml

from cli import CONFIG_FILE
from io.logger import LOGGER

# get Config from yml file
LOGGER.debug('Loading config file...')
try:
    with open(CONFIG_FILE, 'r') as f:
        CONFIG:dict = yaml.load(f, Loader=yaml.FullLoader)
except FileNotFoundError:
    LOGGER.exception('Config File not Found:', CONFIG_FILE); exit()

# Pretalx-Section
JSON_URL: Final[str] = CONFIG['pretalx']['json_url']
CACHE_TIME: Final[str] = CONFIG['pretalx']['cache_time']