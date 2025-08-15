from datetime import date, timedelta, time, datetime

import pytz
import dateutil

from io_config.config import FILTER_TRACKS, FAKE_NOW
from io_config.logger import LOGGER
from pretalx_api_wrapper.pretalx_api import PRETALX


class Track:
    def __init__(self, name:str, color:str):
        self.name = name
        self.color = color

class Conference:
    def __init__(self, data, url) :
        self.data = data
        self.title = data['title']
        self.start = data['start']
        self.end = data['end']
        self.duration = data['daysCount']
        self.url = url
        self.timezone = pytz.timezone(data['time_zone_name'])
        self.colors = data['colors']
        self.tracks = self.filter_tracks()
        self.all_events = self.get_all_events()
        self.ongoing_cache = datetime.now(self.timezone)
        self.ongoing_events = []

    def update(self, data, url) -> None:
        self.data = data
        self.title = data['title']
        self.start = data['start']
        self.end = data['end']
        self.duration = data['daysCount']
        self.url = url
        self.timezone = pytz.timezone(data['time_zone_name'])
        self.colors = data['colors']
        self.tracks = self.filter_tracks()
        self.all_events = self.get_all_events()

    def get_all_events(self) -> list:
        self.all_events = []
        for day in self.data['days']:
            for name, day_events in day['rooms'].items():
                self.all_events.extend(day_events)
        return self.all_events

    def filter_tracks(self):
        if FILTER_TRACKS is not None:
            filtered_tracks = []
            for track in self.data['tracks']:
                if track['name'] not in FILTER_TRACKS:
                    filtered_tracks.append(Track(name=track['name'], color=track['color']))
            LOGGER.info(f"Using filtered tracks: {[t.name for t in filtered_tracks]}")
            return filtered_tracks
        else:
            LOGGER.info(f"Using all tracks: {self.data['tracks']}")
            return [Track(name=track['name'], color=track['color']) for track in self.data['tracks']]

    def get_event_by_id(self, room_id:str):
        for event in self.all_events:
            if event['code'] == room_id:
                if event_in_tracks(self.tracks, event):
                    return event
                else:
                    LOGGER.error(f"Event {event['track']} not found in {self.tracks}")
                    return event
        raise EventNotFoundError(f"No Event found with this id: {room_id}")

    def update_ongoing_events(self) -> bool:
        # Returns a list of ongoing events in this conference sorted by time
        LOGGER.debug("Searching ongoing_events...")
        if self.ongoing_cache > datetime.now(self.timezone) and self.ongoing_events != []:
            return False
        if PRETALX.update_data():
            self.update(PRETALX.data['conference'], PRETALX.data['url'])
        self.ongoing_events = []
        for event in self.all_events:
            # Filter Tracks that are specified in config
            # Filter events to only include the ongoing events and those that start in less than 30 minutes
            if event_in_tracks(self.tracks, event) and event_is_ongoing(self.timezone, event):
                self.ongoing_events.append(event)
        self.ongoing_events.sort(key=lambda e: dateutil.parser.isoparse(e['date'])) # Sorts list by date
        LOGGER.info(f"Ongoing Events:\n {[e['title'] for e in self.ongoing_events]}")
        self.ongoing_cache = datetime.now() + timedelta(minutes=5)
        return True


# ---- INITIALIZE SINGLETON ----
CONFERENCE = Conference(PRETALX.data['conference'], PRETALX.data['url'])

# ----- FILTER LOGIC -----

def event_in_tracks(tracks, event) -> bool:
    # Filter Tracks that are specified in config
    for track in tracks:
        if event['track'] == track.name:
            event['track'] = track.__dict__
            return True
    return False

def event_is_ongoing(timezone, event) -> bool:
    today = FAKE_NOW.date() if FAKE_NOW is not None else date.today()
    # Filter Events to today
    if datetime.fromisoformat(event['date']).date() != today:
        return False
    if FAKE_NOW is None:
        time_missing = datetime.now(tz=timezone) - dateutil.parser.isoparse(event['date'])
    else:
        time_missing = FAKE_NOW - dateutil.parser.isoparse(event['date'])
    duration = timedelta(hours=time.fromisoformat(event['duration']).hour,
                         minutes=time.fromisoformat(event['duration']).minute)
    if time_missing.total_seconds() <= (720 * 60) and timedelta(
            minutes=-31) < time_missing < duration:
        return True
    else:
        return False

# ----- CUSTOM EXCEPTIONS ------

class EventNotFoundError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)