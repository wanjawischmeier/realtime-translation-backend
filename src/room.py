import asyncio
import logging
from typing import Callable
from whisperlivekit import AudioProcessor

from connection_manager import ConnectionManager
from transcription_manager import TranscriptionManager
from translation_worker import TranslationWorker
from whisperlivekit import TranscriptionEngine
from io_config.cli import MODEL, DEVICE, COMPUTE_TYPE, DIARIZATION, VAC, BUFFER_TRIMMING, MIN_CHUNK_SIZE, VAC_CHUNK_SIZE
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
        self._deactivation_task: asyncio.Task = None
    
    def get_data(self):
        data = {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'track': self.track,
            'location': self.location,
            'presenter': self.presenter,
            'active': self.active
        }

        if self.active:
            data['source_lang'] = self.transcription_manager.source_lang
        return data
    
    async def activate(self, source_lang:str, target_langs: list[str], connection_manager: ConnectionManager=None):
        logging.info(f'Activating self: {self.id}')
        self.active = True
        if self._deactivation_task:
            self._deactivation_task.cancel() # Cancel room deactivation
            self._deactivation_task = None
        
        LOGGER.info(f'Loading whisper model for {self.id}: {MODEL}, diarization={DIARIZATION}, language={source_lang}')
        self.transcription_engine = transcription_engine = TranscriptionEngine(
            model=MODEL, diarization=DIARIZATION, lan=source_lang,
            vac=VAC, buffer_trimming=BUFFER_TRIMMING,
            min_chunk_size=MIN_CHUNK_SIZE, vac_chunk_size=VAC_CHUNK_SIZE,
            device=DEVICE, compute_type=COMPUTE_TYPE
        )
        self.transcription_manager = TranscriptionManager(source_lang, self_id=self.id)
            
        self.audio_processor = AudioProcessor(transcription_engine=transcription_engine)
        whisper_generator = await self.audio_processor.create_tasks()
        
        if connection_manager:
            self.connection_manager = connection_manager
        else:
            self.connection_manager = ConnectionManager(self.transcription_manager, self.audio_processor, whisper_generator,
                                                        self.audio_processor.process_audio, self.transcription_manager.submit_chunk,
                                                        self.restart_engine)
        self.translation_worker = TranslationWorker(self.transcription_manager, target_langs=target_langs)
        self.translation_worker.start()
    
    async def deactivate(self) -> bool:
        if not self.active:
            LOGGER.warning(f'Tried to deactivate inactive room <{self.id}>')
            return False
            
        # TODO: properly close room
        await self.collect()
        self.connection_manager.cancel()
        self.active = False
        return True
    
    async def collect(self):
        self.transcription_engine.free()
        # await self.audio_processor.cleanup() # 'NoneType' object has no attribute 'sep' in audio_processor.watchdog
        self.translation_worker.stop()

    async def defer_deactivation(self, on_deactivate: Callable[[None], None], deactivation_delay: float=300):
        # Cancel any existing deactivation task
        if self._deactivation_task:
            self._deactivation_task.cancel()
            self._deactivation_task = None
        
        # Start new delayed deactivation
        async def deactivate_after_delay():
            await asyncio.sleep(deactivation_delay)
            self._deactivation_task = None
            on_deactivate(self)
            LOGGER.info(f'Deactivating room <{self.id}> after {deactivation_delay}s without host')
            await self.deactivate()
        
        self._deactivation_task = asyncio.create_task(
            deactivate_after_delay()
        )
    
    async def restart_engine(self) -> bool:
        if not self.active:
            LOGGER.warning(f'Tried to restart inactive room <{self.id}>')
            return False
        
        self.collect(self)
        self.activate(self, self.transcription_manager.source_lang,
                            self.translation_worker.target_langs,
                            self.connection_manager # Preserve ws connections across restart
        )
        return True
