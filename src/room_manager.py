import logging
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from whisperlivekit import AudioProcessor

from connection_manager import ConnectionManager
from io_config.config import AVAILABLE_LANGS
from pretalx_api_wrapper import PretalxAPI
from transcription_manager import TranscriptionManager
from io_config.logger import LOGGER
from translation_worker import TranslationWorker


class Room:
    def __init__(self, room_id:str, title: str, track:str, location:str, url:str, description:str, organizer:str, do_not_record:bool,
                 transcription_manager:TranscriptionManager=None, connection_manager:ConnectionManager=None, audio_processor:AudioProcessor=None, translation_worker:TranslationWorker=None):
        self.id = room_id
        self.title = title
        self.track = track
        self.location = location
        self.pretalx_url = url
        self.active = False
        self.do_not_record = do_not_record
        self.organizer = organizer
        self.description = description
        self.transcription_manager:TranscriptionManager = transcription_manager
        self.connection_manager:ConnectionManager = connection_manager
        self.audio_processor:AudioProcessor = audio_processor
        self.translation_worker:TranslationWorker = translation_worker
    
    def get_data(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'track': self.track,
            'location': self.location,
            'organizer': self.organizer,
            'active': self.active,
            'available_langs': AVAILABLE_LANGS
        }


class RoomManager:
    def __init__(self, pretalx:PretalxAPI):
        self.pretalx = pretalx
        self.current_rooms: list[Room] = []
        self.update_rooms()

    def update_rooms(self):
        self.pretalx.get_ongoing_events()
        self.current_rooms.clear()
        for event in self.pretalx.ongoing_events:
            room = Room(event['code'], event['title'], event['track'], event['room'], event['url'], event['description'],
                event['persons'][0]['name'], event['do_not_record'])
            self.current_rooms.append(room)
        self.current_rooms.append(Room("dev_room_id", "dev_titel", "dev_track","dev_room", "dev_url","dev_des", "bob", False))
    
    async def activate_room(self, websocket: WebSocket, room_id:str, source_lang:str, transcription_engine):
        for room in self.current_rooms:
            if room_id != room.id:
                continue

            logging.info(f'Activating room: {room_id}')
            room.active = True
            room.transcription_manager = TranscriptionManager(source_lang, room_id=room_id)
            
            room.audio_processor = AudioProcessor(transcription_engine=transcription_engine)
            whisper_generator = await room.audio_processor.create_tasks()

            room.connection_manager = ConnectionManager(room.transcription_manager, room.audio_processor, whisper_generator)
            room.translation_worker = TranslationWorker(room.transcription_manager)
            await room.connection_manager.listen_to_host(websocket)

            self.deactivate_room(room_id)
            break

    async def join_room_as_client(self, websocket: WebSocket, room_id:str, target_lang:str):
        for room in self.current_rooms:
            if room_id != room.id:
                continue

            if not room.active:
                LOGGER.warning(f'Client connection failed: Room not active')
                await websocket.close(code=1003, reason='Room not active')
                return


            logging.info(f'Client joining room: {room_id}')
            try:
                await room.connection_manager.connect_client(websocket)
                room.translation_worker.target_langs.append(target_lang)
                LOGGER.info(f"Added {target_lang} to {room_id}.")
            except Exception as e:
                LOGGER.warning(f'Client connection failed:\n{e}')
                await websocket.close(code=1003, reason="Internal server error")
            
            break


    def deactivate_room(self, room_id:str):
        for room in self.current_rooms:
            if room_id != room.id:
                continue
            
            # TODO: properly close room
            room.transcription_manager = None
            room.connection_manager = None
            room.active = False

            break

    def get_room_list(self):
        return [room.get_data() for room in self.current_rooms]

room_manager = RoomManager(pretalx=PretalxAPI())
