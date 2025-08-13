from datetime import date, datetime, timedelta, time

import pytz
import dateutil.parser
import requests

from io_config.config import JSON_URL, CACHE_TIME
from io_config.logger import LOGGER


class Track:
    def __init__(self, name:str, color:str):
        self.name = name
        self.color = color

class Conference:
    def __init__(self, title: str, start: date, end: date, days: int, url: str, timezone: pytz.BaseTzInfo,
                 colors: dict, tracks: list[Track]):
        self.title = title
        self.start = start
        self.end = end
        self.days = days
        self.url = url
        self.timezone = timezone
        self.colors = colors
        self.tracks = tracks # Tracks are type of events

class PretalxAPI:
    def __init__(self):
        self.json_url = JSON_URL
        self.cache_time: datetime = datetime.now()
        self.data: dict = {}
        self.update_data()
        self.conference: Conference = self.get_conference()
        LOGGER.info(f"Conference Infos:\n {self.conference.__dict__}")
        self.ongoing_events = []

    def update_data(self):
        # Retrieves Data from Pretalx-Server (Should be called regularly)
        if self.cache_time > datetime.now():
            LOGGER.debug(f"Using cached pretalx data...")
            return
        LOGGER.info(f"Updating and caching data from pretalx @ {self.json_url}...")
        response = requests.get(self.json_url)
        if response.status_code != 200:
            raise APIError("Server returned HTTP status {code}".format(code=response.status_code))
        self.data = response.json()['schedule']
        self.cache_time = datetime.now() + timedelta(minutes=CACHE_TIME)

    def get_conference(self) -> Conference:
        # Parses Data necessary to display the Conference in a nice way
        LOGGER.debug(f"Parsing Conference data...")
        url = self.data['url']
        data = self.data['conference']
        tracks = [Track(name=track['name'], color=track['color']) for track in data['tracks']]
        return Conference(title=data['title'], start=data['start'], end=data['end'], days=data['daysCount'], url=url, timezone=pytz.timezone(data['time_zone_name']), colors=data['colors'], tracks=tracks)

    def get_ongoing_events(self, fake_now:str=None):
        # Returns a list of ongoing events in this conference sorted by time
        self.update_data()
        LOGGER.debug("Searching ongoing_events...")
        self.ongoing_events = []
        today = datetime.fromisoformat(fake_now).date() if fake_now is not None else date.today()
        for day in self.data['conference']['days']:
            for name, events in day['rooms'].items():
                for event in events:
                    # Filter Events to specific day (today)
                    if datetime.fromisoformat(event['date']).date() != today:
                        continue
                    # Filter events to only ongoing events
                    now = datetime.now(tz=self.conference.timezone)
                    duration = timedelta(hours=time.fromisoformat(event['duration']).hour, minutes=time.fromisoformat(event['duration']).minute)
                    if fake_now is None:
                        now_start_delta = (now - dateutil.parser.isoparse(event['date']))
                    else:
                        now_start_delta  = (datetime.fromisoformat(fake_now) - dateutil.parser.isoparse(event['date']))
                    # Filter events to only include the ongoing events and those that start in less than 30 minutes
                    if now_start_delta.total_seconds() <= (720 * 60) and timedelta(minutes=-31) < now_start_delta < duration:
                         self.ongoing_events.append(event)
        self.ongoing_events.sort(key=lambda e: dateutil.parser.isoparse(e['date'])) # Sorts list by date
        LOGGER.info(f"Ongoing Events:\n {[e for e in self.ongoing_events]}")

    def get_event_by_id(self, room_id:str):
        for day in self.data['conference']['days']:
            for name, events in day['rooms'].items():
                for event in events:
                    if event['code'] == room_id:
                        return event
        raise APIError(f"No Event found with this id: {room_id}")


class APIError(Exception):
    pass

"""
# Usage Example
pretalx = PretalxAPI()
print(pretalx.conference.__dict__)
pretalx.get_ongoing_events(fake_now='2025-08-20T16:00:00+02:00')
[print(e) for e in pretalx.ongoing_events]
print(pretalx.get_event_by_id("ECUGNH"))
"""