# TODO Add Class for Rooms
# TODO ADD methods to manage rooms
import websocket
from whisperlivekit import AudioProcessor
from whisperlivekit.basic_server import transcription_engine

from src.connection_manager import ConnectionManager
from src.pretalx_api_wrapper import PretalxAPI
from src.transcription_manager import TranscriptionManager
from src.whisper_server import args


class Room:
    def __init__(self, code:str, title: str, track:str, location:str, url:str, description:str, organizer:str, do_not_record:bool):
        self.id = code
        self.title = title
        self.track = track
        self.location = location
        self.pretalx_url = url
        self.active = False
        self.do_not_record = do_not_record
        self.organizer = organizer
        self.description = description
        self.transcription_manager:TranscriptionManager = None


class RoomManager:
    def __init__(self, pretalx:PretalxAPI):
        self.pretalx = pretalx
        self.pretalx.get_ongoing_events(fake_now='2025-08-20T16:00:00+02:00')
        self.current_rooms = []
        self.update_rooms()

    def update_rooms(self):
        self.pretalx.get_ongoing_events()
        self.current_rooms.clear()
        for event in self.pretalx.ongoing_events:
            room = Room(event['code'], event['title'], event['track'], event['room'], event['url'], event['description'],
                event['persons'][0]['name'], event['do_not_record'])
            self.current_rooms.append(room)

    def activate_room(self, room_id:str, source_lang:str):
        for room in self.current_rooms:
            if room_id != room.id:
                continue
            else:
                room.active = True
                room.transcription_manager = TranscriptionManager(source_lang)

room_manager = RoomManager(pretalx=PretalxAPI())

class RoomManager2:
    def __init__(self, transcription_managers: list[TranscriptionManager]):
        self.transcription_managers = transcription_managers
