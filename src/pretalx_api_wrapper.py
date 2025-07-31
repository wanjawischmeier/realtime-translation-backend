from datetime import date, datetime, timedelta, time
import dateutil.parser
import pytz
import requests


class Track:
    def __init__(self, name:str, color:str):
        self.name = name
        self.color = color

class Conference:
    def __init__(self, title: str, start: date, end: date, days: int, url: str, timezone: pytz.tzinfo,
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
    def __init__(self, json_url):
        self.json_url = 'https://programm.infraunited.org/scc-25-2025/schedule/export/schedule.json' #TODO move to config at some point
        self.data: dict = self.get_data()
        self.conference: Conference = self.get_conference()
        self.ongoing_events = []

    def get_data(self) -> dict:
        # Retrieves Data from Pretalx-Server
        response = requests.get(self.json_url)
        if response.status_code != 200:
            raise APIError("Server returned HTTP status {code}".format(code=response.status_code))
        return response.json()['schedule']

    def get_conference(self) -> Conference:
        # Parses Data necessary to display the Conference in a nice way
        url = self.data['url']
        data = self.data['conference']
        tracks = [Track(name=track['name'], color=track['color']) for track in data['tracks']]
        return Conference(title=data['title'], start=data['start'], end=data['end'], days=data['daysCount'], url=url, timezone=pytz.timezone(data['time_zone_name']), colors=data['colors'], tracks=tracks)

    def get_ongoing_events(self, fake_now:str=None):
        # Returns a list of ongoing events in this conference sorted by time
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

class APIError(Exception):
    pass

# Usage EXample
pretalx = PretalxAPI(json_url='https://programm.infraunited.org/scc-25-2025/schedule/export/schedule.json')
print(pretalx.conference.__dict__)
pretalx.get_ongoing_events(fake_now='2025-08-20T16:00:00+02:00')
[print(e) for e in pretalx.ongoing_events]