from typing import Final

import requests
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

HOST_PASSWORD: Final[str] = CONFIG['host_password']
ADMIN_PASSWORD: Final[str] = CONFIG['admin_password']

# Pretalx-Section
JSON_URL: Final[str] = CONFIG['pretalx']['json_url']
CACHE_TIME: Final[int] = CONFIG['pretalx']['cache_time']

# FastAPI-Section
API_HOST: Final[str] = CONFIG['fastapi']['host']
API_PORT: Final[int] = CONFIG['fastapi']['port']

# Whisper-Section
AVAILABLE_WHISPER_LANGS: Final[str] = CONFIG['whisper']['langs']
MAX_WHISPER_INSTANCES: Final[int] = CONFIG['whisper']['max_instances']
CLOSE_ROOM_AFTER_SECONDS: Final[int] = CONFIG['whisper']['close_room_after_seconds']

# LibreTranslate-Section
LT_HOST: Final[str] = CONFIG['libretranslate']['host']
LT_PORT: Final[int] = CONFIG['libretranslate']['port']
LT_LANGS: Final[str] = CONFIG['libretranslate']['langs']
def get_available_languages():
    # Get Available Languages from libretranslate.com
    LOGGER.info(f"Getting available languages from {LT_LANGS}...")
    response = requests.get(LT_LANGS)
    if response.status_code != 200:
        LOGGER.error("Server returned HTTP status {code}".format(code=response.status_code))
    return response.json()[0]['targets']
AVAILABLE_LT_LANGS: Final[list[str]] = get_available_languages()

# Data-Section
TRANSCRIPT_DB_DIRECTORY: Final[str] = CONFIG['data']['transcript_db_directory']
