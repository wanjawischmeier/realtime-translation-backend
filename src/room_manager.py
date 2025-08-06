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
    def __init__(self, room_id:str, title: str, track:str, location:str, url:str, description:str, presenter:str, do_not_record:bool,
                 transcription_manager:TranscriptionManager=None, connection_manager:ConnectionManager=None, audio_processor:AudioProcessor=None, translation_worker:TranslationWorker=None):
        self.id = room_id
        self.title = title
        self.track = track
        self.location = location
        self.pretalx_url = url
        self.active = False
        self.do_not_record = do_not_record
        self.presenter = presenter
        self.description = description
        self.transcription_manager:TranscriptionManager = transcription_manager
        self.connection_manager:ConnectionManager = connection_manager
        self.audio_processor:AudioProcessor = audio_processor
        self.translation_worker:TranslationWorker = translation_worker
    
    def get_data(self):
        data = {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'track': self.track,
            'location': self.location,
            'presenter': self.presenter,
            'active': self.active,
            'available_langs': AVAILABLE_LANGS
        }

        if self.active:
            data['source_lang'] = self.transcription_manager.source_lang
        return data


class RoomManager:
    def __init__(self, pretalx:PretalxAPI):
        self.pretalx = pretalx
        self.current_rooms: list[Room] = []
        self.update_rooms()

    def get_room(self, room_id: str) -> Room:
        for room in self.current_rooms:
            if room_id != room.id:
                continue
            
            return room
        
        return None

    def update_rooms(self):
        self.pretalx.get_ongoing_events()
        self.current_rooms.clear()
        for event in self.pretalx.ongoing_events:
            room = Room(event['code'], event['title'], event['track'], event['room'], event['url'], event['description'],
                event['persons'][0]['name'], event['do_not_record'])
            self.current_rooms.append(room)
        self.current_rooms.append(Room("dev_room_id", "dev_titel", "dev_track","dev_room", "dev_url","dev_des", "bob", False))
    
    async def activate_room_as_host(self, websocket: WebSocket, room_id:str, source_lang:str, target_lang: str, transcription_engine):
        room = self.get_room(room_id)
        if not room:
            await websocket.close(code=1003, reason=f'Room "{room_id}" not found')
            return

        logging.info(f'Activating room: {room_id}')
        room.active = True
        room.transcription_manager = TranscriptionManager(source_lang, room_id=room_id)
            
        room.audio_processor = AudioProcessor(transcription_engine=transcription_engine)
        whisper_generator = await room.audio_processor.create_tasks()

        room.connection_manager = ConnectionManager(room.transcription_manager, room.audio_processor, whisper_generator)
        room.translation_worker = TranslationWorker(room.transcription_manager)
        room.translation_worker.target_langs.append(target_lang)
        room.translation_worker.start()
        await room.connection_manager.listen_to_host(websocket)

        # Host disconnected
        self.deactivate_room(room_id)

    async def join_room_as_client(self, websocket: WebSocket, room_id:str, target_lang:str):
        room = self.get_room(room_id)
        if not room:
            await websocket.close(code=1003, reason=f'Room "{room_id}" not found')
            return

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

    def deactivate_room(self, room_id:str) -> bool:
        room = self.get_room(room_id)
        if not room:
            LOGGER.warning("Tried to deactivate unknown room id")
            return False
        
        if not room.active:
            LOGGER.warning("Tried to deactivate inactive room")
            return False
            
        # TODO: properly close room
        room.translation_worker.stop()
        room.active = False
        return True

    def get_room_list(self):
        return [room.get_data() for room in self.current_rooms]

room_manager = RoomManager(pretalx=PretalxAPI())
