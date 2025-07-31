import enum

import dateutil.parser
import requests
import datetime
import pytz

class Conference:
    def __init__(self, title: str, start: datetime.date, end: datetime.date, days: int, url: str, timezone: pytz.tzinfo,
                 colors: dict, tracks: list[dict[str, str]]):
        self.title = title
        self.start = start
        self.end = end
        self.days = days
        self.url = url
        self.timezone = timezone
        self.colors = colors
        self.tracks = tracks

class PretalxAPI:
    def __init__(self, json_url):
        self.json_url = 'https://programm.infraunited.org/scc-25-2025/schedule/export/schedule.json'
        self.conference = None

    def get_conference(self):
        response = requests.get(self.json_url)
        if response.status_code != 200:
            raise APIError("Server returned HTTP status {code}".format(code=response.status_code))
        schedule:dict = response.json()['schedule']
        data = schedule['conference']
        url = schedule['url']
        tracks = [dict(name=track['name'], color=track['color']) for track in data['tracks']]
        conference = Conference(title=data['title'], start=data['start'], end=data['end'], days=data['daysCount'], url=url, timezone=data['time_zone_name'], colors=data['colors'], tracks=tracks)
        self.conference = conference


class APIError(Exception):
    pass


pretalx_api = PretalxAPI(json_url='https://programm.infraunited.org/scc-25-2025/schedule/export/schedule.json')
pretalx_api.get_conference()