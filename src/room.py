import asyncio
from typing import Callable

from connection_manager import ConnectionManager
from transcription_manager import TranscriptionManager
from translation_worker import TranslationWorker
from room_process import RoomProcess
from io_config.logger import LOGGER

class Room:
    def __init__(self, room_id:str, title: str, track:str, location:str, url:str, description:str, presenter:str, do_not_record:bool, active=False,
                 transcription_manager:TranscriptionManager=None, connection_manager:ConnectionManager=None, translation_worker:TranslationWorker=None):
        
        self.id = room_id
        self.title = title
        self.track = track
        self.location = location
        self.pretalx_url = url
        self.active = active
        self.do_not_record = do_not_record
        self.presenter = presenter
        self.description = description
        self.transcription_manager: TranscriptionManager = transcription_manager
        self.connection_manager: ConnectionManager = connection_manager
        self.translation_worker: TranslationWorker = translation_worker
        self._deactivation_task: asyncio.Task = None
        self._room_process: RoomProcess = None
    
    def get_data(self):
        host_connection_id = ''
        if self.connection_manager:
            if self.connection_manager.host_id:
                host_connection_id = self.connection_manager.host_id
        
        data = {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'track': self.track,
            'location': self.location,
            'presenter': self.presenter,
            'host_connection_id': host_connection_id
        }

        if self.active:
            data['source_lang'] = self.transcription_manager.source_lang
        return data
    
    async def activate(self, source_lang: str, target_langs: dict[str, int], connection_manager: ConnectionManager=None):
        LOGGER.info(f'Activating room <{self.id}>')
        self.active = True
        if self._deactivation_task:
            self._deactivation_task.cancel() # Cancel room deactivation
            self._deactivation_task = None

        self.transcription_manager = TranscriptionManager(source_lang, room_id=self.id)
        self._room_process = RoomProcess(self.id, source_lang)
        self.translation_worker = TranslationWorker(self.transcription_manager, target_langs=target_langs)
        self.translation_worker.start()
        
        if connection_manager:
            # Update fields
            connection_manager.transcription_manager = self.transcription_manager
            connection_manager.translation_worker = self.translation_worker
            connection_manager.audio_chunk_recieved = self._room_process.send_audio_chunk
            connection_manager.transcript_chunk_recieved = self.transcription_manager.submit_chunk
            connection_manager.transcript_chunk_provider = self._room_process.get_transcript_chunk
            self.connection_manager = connection_manager
        else:
            self.connection_manager = ConnectionManager(
                self.id, self.transcription_manager, self.translation_worker,
                audio_chunk_recieved=self._room_process.send_audio_chunk,  # async proxy!
                transcript_chunk_recieved=self.transcription_manager.submit_chunk,
                transcript_chunk_provider=self._room_process.get_transcript_chunk,
                host_signal_recieved=self.handle_host_signal
            )
        
        # Start the room subprocess (needs connection manager to be initialized)
        self._room_process.start(self.connection_manager.ready_to_recieve_audio)
    
    async def deactivate(self) -> bool:
        if not self.active:
            LOGGER.warning(f'Tried to deactivate inactive room <{self.id}>')
            return False
            
        # TODO: properly close room
        await self.cancel()
        self.connection_manager.dereference_host()
        self.active = False
        return True
    
    async def cancel(self):
        self.connection_manager.cancel()
        self.translation_worker.stop()
        await self._room_process.stop()

    def defer_deactivation(self, on_deactivate: Callable[[None], None], deactivation_delay: float=300):
        # Cancel any existing deactivation task
        if self._deactivation_task:
            self._deactivation_task.cancel()
            self._deactivation_task = None
        
        # Start new delayed deactivation
        async def deactivate_after_delay():
            await asyncio.sleep(deactivation_delay)
            self._deactivation_task = None
            on_deactivate()
            LOGGER.info(f'Deactivating room <{self.id}> after {deactivation_delay}s without host')
            await self.deactivate()
        
        self._deactivation_task = asyncio.create_task(
            deactivate_after_delay()
        )
    
    async def restart_engine(self, source_lang: str=None, target_langs: list[str]=None) -> bool:
        if not self.active:
            LOGGER.warning(f'Tried to restart inactive room <{self.id}>')
            return False
        
        if not source_lang:
            source_lang = self.transcription_manager.source_lang
        if not target_langs:
            target_langs = self.translation_worker.target_langs

        LOGGER.warning(f'Restarting backend for room <{self.id}>...')
        await self.cancel()
        await self.activate(source_lang, target_langs, self.connection_manager) # Preserves ws connections across restart
        return True
    
    async def handle_host_signal(self, signal: str):
        LOGGER.info(f'Recieved signal in room <{self.id}>: {signal}')
        if signal == 'restart_backend_engine':
            await self.restart_engine()
            await self.connection_manager.listen_to_host() # TODO: Refactor to not recursively call listen_to_host
