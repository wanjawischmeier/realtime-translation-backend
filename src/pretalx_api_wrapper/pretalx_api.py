from datetime import datetime, timedelta

import requests

from io_config.config import JSON_URL, CACHE_TIME
from io_config.logger import LOGGER

class PretalxAPI:
    def __init__(self):
        self.json_url = JSON_URL
        self.cache_time: datetime = datetime.now()
        self.data: dict = {}
        self.get_data()

    def get_data(self) -> dict:
        response = requests.get(self.json_url)
        if response.status_code != 200:
            raise APIError("Server returned HTTP status {code}".format(code=response.status_code))
        self.data = response.json()['schedule']
        self.cache_time = datetime.now() + timedelta(minutes=CACHE_TIME)
        return self.data

    def update_data(self) -> bool:
        # Retrieves Data from Pretalx-Server (Should be called regularly)
        if self.cache_time > datetime.now() and self.data != {}:
            LOGGER.debug(f"Using cached pretalx data...")
            return False
        LOGGER.info(f"Updating and caching data from pretalx @ {self.json_url}...")
        self.get_data()
        return True

class APIError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

# ---- INITIALIZE SINGLETON ----
PRETALX = PretalxAPI()
