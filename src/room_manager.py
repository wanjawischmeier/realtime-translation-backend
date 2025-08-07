import asyncio
import logging
from fastapi import WebSocket
from whisperlivekit import AudioProcessor

from connection_manager import ConnectionManager
from pretalx_api_wrapper import PretalxAPI
from transcription_manager import TranscriptionManager
from translation_worker import TranslationWorker
from whisperlivekit import TranscriptionEngine
from io_config.cli import MODEL, DIARIZATION
from io_config.config import AVAILABLE_WHISPER_LANGS, AVAILABLE_LT_LANGS
from io_config.logger import LOGGER


class Room:
    def __init__(self, room_id:str, title: str, track:str, location:str, url:str, description:str, presenter:str, do_not_record:bool, active=False,
                 transcription_engine: TranscriptionEngine = None, transcription_manager:TranscriptionManager=None,
                 connection_manager:ConnectionManager=None, audio_processor:AudioProcessor=None, translation_worker:TranslationWorker=None):
        
        self.id = room_id
        self.title = title
        self.track = track
        self.location = location
        self.pretalx_url = url
        self.active = active
        self.do_not_record = do_not_record
        self.presenter = presenter
        self.description = description
        self.transcription_engine: TranscriptionEngine = transcription_engine
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
            'available_source_langs': AVAILABLE_WHISPER_LANGS, # TODO: put in a more reasonable data structure
            'available_target_langs': AVAILABLE_LT_LANGS
        }

        if self.active:
            data['source_lang'] = self.transcription_manager.source_lang
        return data


class RoomManager:
    def __init__(self, pretalx:PretalxAPI):
        self.pretalx = pretalx
        self.current_rooms: list[Room] = []
        self._deactivation_tasks: dict[str, asyncio.Task] = {}
        self.update_rooms()

    def get_room(self, room_id: str) -> Room | None:
        for room in self.current_rooms:
            if room_id != room.id:
                continue
            
            return room

    def update_rooms(self):
        self.pretalx.get_ongoing_events()
        self.current_rooms.clear()
        for event in self.pretalx.ongoing_events:
            room = Room(event['code'], event['title'], event['track'], event['room'], event['url'], event['description'],
                event['persons'][0]['name'], event['do_not_record'])
            self.current_rooms.append(room)
        self.current_rooms.append(Room('dev_room_id', 'dev_titel', 'dev_track','dev_room', 'dev_url','dev_des', 'bob', False))
    
    async def activate_room_as_host(self, websocket: WebSocket, room_id:str, source_lang:str, target_lang: str):
        room = self.get_room(room_id)
        if not room:
            await websocket.close(code=1003, reason=f'Room <{room_id}> not found')
            return
        
        if room.do_not_record:
            await websocket.close(code=1003, reason=f'Audio recording not allowed in room <{room_id}>')
            return
        
        if not source_lang in AVAILABLE_WHISPER_LANGS:
            await websocket.close(code=1003, reason=f'Source language {source_lang} not supported by transcription engine')
            return
        
        if not target_lang in AVAILABLE_LT_LANGS:
            await websocket.close(code=1003, reason=f'Target language {target_lang} not supported by translation service')
            return
        
        if room.active:
            if source_lang == room.transcription_manager.source_lang:
                # Matching configuration
                if not target_lang in room.translation_worker.target_langs:
                    room.translation_worker.target_langs.append(target_lang)
                
                LOGGER.info(f'Host joined already active room <{room_id}> with matching configuration')
            else:
                # Configuration mismatch, restart room
                LOGGER.info(f'Host joined already active room <{room_id}> with mismatching configuration, restarting room...')
                self._deactivate_room(room)
                await self._activate_room(room, source_lang, target_lang)
        else:
            # Initial room activation
            await self._activate_room(room, source_lang, target_lang)

        # TODO: send 'now listening' to frontend
        await room.connection_manager.listen_to_host(websocket)

        # Host disconnected
        self.defer_room_deactivation(room_id)

    async def join_room_as_client(self, websocket: WebSocket, room_id:str, target_lang:str):
        room = self.get_room(room_id)
        if not room:
            await websocket.close(code=1003, reason=f'Room <{room_id}> not found')
            return

        if not room.active:
            LOGGER.warning(f'Client connection failed: Room not active')
            await websocket.close(code=1003, reason='Room not active')
            return

        logging.info(f'Client joining room: {room_id}')
        try:
            await room.connection_manager.connect_client(websocket)
            room.translation_worker.target_langs.append(target_lang)
            LOGGER.info(f'Added {target_lang} to {room_id}.')
        except Exception as e:
            LOGGER.warning(f'Client connection failed:\n{e}')
            await websocket.close(code=1003, reason='Internal server error')

    async def _activate_room(self, room: Room, source_lang:str, target_lang: str):
        logging.info(f'Activating room: {room.id}')
        room.active = True
        task = self._deactivation_tasks.get(room.id, None)
        if task:
            task.cancel() # Cancel room deactivation
        LOGGER.info(f'Loading whisper model for {room.id}: {MODEL}, diarization={DIARIZATION}, language={source_lang}')
        room.transcription_engine = transcription_engine = TranscriptionEngine(model=MODEL, diarization=DIARIZATION, lan=source_lang)
        room.transcription_manager = TranscriptionManager(source_lang, room_id=room.id)
            
        room.audio_processor = AudioProcessor(transcription_engine=transcription_engine)
        whisper_generator = await room.audio_processor.create_tasks()

        room.connection_manager = ConnectionManager(room.transcription_manager, room.audio_processor, whisper_generator)
        room.translation_worker = TranslationWorker(room.transcription_manager)
        if not target_lang in room.translation_worker.target_langs:
            room.translation_worker.target_langs.append(target_lang)
        room.translation_worker.start()

    def _deactivate_room(self, room: Room) -> bool:
        if not room.active:
            LOGGER.warning(f'Tried to deactivate inactive room <{room.id}>')
            return False
            
        # TODO: properly close room
        room.connection_manager.cancel()
        room.translation_worker.stop()
        room.active = False
        return True

    async def defer_room_deactivation(self, room_id: str, deactivation_delay: float=300):
        # Cancel any existing deactivation task
        task = self._deactivation_tasks.pop(room_id, None)
        if task:
            task.cancel()
        
        # Start new delayed deactivation
        async def deactivate_after_delay():
            await asyncio.sleep(deactivation_delay)
            self._deactivation_tasks.pop(room_id, None)
            LOGGER.info(f'Deactivating room <{room_id}> after {deactivation_delay}s without host')
            self._deactivate_room(room_id)
        self._deactivation_tasks[room_id] = asyncio.create_task(
            deactivate_after_delay()
        )

    def get_room_list(self):
        return [room.get_data() for room in self.current_rooms]

room_manager = RoomManager(pretalx=PretalxAPI())
