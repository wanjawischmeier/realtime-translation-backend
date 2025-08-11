import asyncio
from types import CoroutineType
from typing import Any, Awaitable, Callable
import uuid
from fastapi import WebSocket, WebSocketDisconnect
from flask import json

from io_config.logger import LOGGER
from transcription_system.transcription_manager import TranscriptionManager
from translation_worker import TranslationWorker


class ConnectionManager:
    def __init__(
            self, room_id: str,
            transcription_manager: TranscriptionManager,
            translation_worker: TranslationWorker,
            audio_chunk_recieved: Callable[[Any], Awaitable[None]],     # async -> send_audio_chunk
            transcript_chunk_recieved: Callable[[dict], None],          # sync  -> transcription_manager.submit_chunk
            transcript_chunk_provider: CoroutineType,                   # async -> get_transcript_chunk
            host_signal_recieved: Callable[[str], bool]
        ):
        self._room_id = room_id
        self.transcription_manager = transcription_manager
        self.translation_worker = translation_worker
        self.audio_chunk_recieved = audio_chunk_recieved
        self.transcript_chunk_recieved = transcript_chunk_recieved
        self.transcript_chunk_provider = transcript_chunk_provider
        self._host_signal_recieved = host_signal_recieved
        self._host: WebSocket = None
        self.host_id: str = None
        self._clients: list[WebSocket] = []

    async def listen_to_host(self, host: WebSocket=None, target_lang: str=None):
        if not host:
            if not self._host:
                LOGGER.error(f'Unable to listen to host in room <{self._room_id}>: Unknown host')
                await host.close(code=1003, reason='No host provided by manager (internal error)')
                return
            # Otherwise use existing host connection
        elif self._host: # Can't connect to multiple hosts at the same time
            await host.close(code=1003, reason='Multiple hosts not allowed')
            return
        else:
            # Establish new host connection
            self._host = host
            self.host_id = str(uuid.uuid4())
            await self._host.send_json({'info': {
                'connection_id': self.host_id
            }})
        
        if target_lang:
            self.translation_worker.subscribe_target_lang(target_lang)
        
        self._whisper_generator_handler_task = asyncio.create_task(
            self._handle_whisper_generator()
        )
        self._transcript_generator_handler_task = asyncio.create_task(
            self._handle_transcript_generator(self.transcription_manager.transcript_generator())
        )
        
        await self._host.send_json(self.transcription_manager.last_transcript_chunk) # Inital transcript chunk
        LOGGER.info(f'Host connected in room <{self._room_id}>, listening...')

        try:
            while True:
                if not host:
                    return # Websocket disconnected
                
                data = await host.receive()
                if "bytes" in data:
                    audio_bytes = data["bytes"]
                    await self.audio_chunk_recieved(audio_bytes)
                elif "text" in data:
                    text_data = data["text"]
                    message = json.loads(text_data)
                    if 'signal' in message:
                        signal = message['signal']
                        await self._host_signal_recieved(signal)
                    else:
                        LOGGER.warning(f'Recieved unknown json object in room <{self._room_id}>')
                elif 'type' in data:
                    if data['type'] == 'websocket.disconnect':
                        raise WebSocketDisconnect(data['code'], data['reason'])
                else:
                    LOGGER.warning(f'Recieved data in unknown format from host of room <{self._room_id}>:\n{data}')
        except WebSocketDisconnect:
            LOGGER.info(f'Host disconnected in room <{self._room_id}>')
            self.cancel()
            self._host = None
            if target_lang:
                self.translation_worker.unsubscribe_target_lang(target_lang)
        except RuntimeError as error:
            LOGGER.warning(f'Runtime errror whilst listening to host in room <{self._room_id}>:\n{error}')
    
    def dereference_host(self):
        self.host_id = ''
        
    async def connect_client(self, client: WebSocket, target_lang: str):
        self._clients.append(client)
        await client.send_json(self.transcription_manager.last_transcript_chunk) # Inital transcript chunk
        LOGGER.info(f'Client {len(self._clients)} connected to room <{self._room_id}>')
        self.translation_worker.subscribe_target_lang(target_lang)

        try:
            while True:
                await client.receive() # Just to check connection, not actually expecting data
        except (WebSocketDisconnect, RuntimeError):
            self._clients.remove(client)
            self.translation_worker.unsubscribe_target_lang(target_lang)
            LOGGER.info(f'Client {len(self._clients) + 1} disconnected in room <{self._room_id}>') # TODO: fix recognition of client detection
    
    async def ready_to_recieve_audio(self, host: WebSocket=None):
        """
        To be called once audio_chunk_recieved is ready to recieve audio chunks 
        """
        if not host:
            if self._host:
                host = self._host
            else:
                LOGGER.error(f'Unable to send "ready_to_recieve_audio" in room <{self._room_id}>: Unknown host')
                return
        
        await host.send_json({'info': {
            'ready_to_recieve_audio': True
        }})
    
    async def _handle_whisper_generator(self):
        while True:
            chunk = await self.transcript_chunk_provider()
            if chunk: # Might be None if chunk contained sentinel value
                self.transcript_chunk_recieved(chunk)
    
    async def _handle_transcript_generator(self, transcript_generator):
        async for transcript in transcript_generator:
            LOGGER.info(f'Result for room <{self._room_id}>:')
            LOGGER.info(transcript)
            
            await self._host.send_json(transcript) # Host also wants to recieve transcript
            for client in self._clients:
                try:
                    await client.send_json(transcript)
                except WebSocketDisconnect:
                    LOGGER.info(f'Removing dead client {len(self._clients)} in room <{self._room_id}>')
                    self._clients.remove(client)
        
        for client in self._clients: # TODO: implement this in the frontend?
            await client.send_json({'type': 'ready_to_stop'})
        LOGGER.info(f'Results generator closed in room <{self._room_id}>')
        self._transcript_generator_handler_task.cancel() # TODO: check if this is necessary/working

    def cancel(self):
        if self._whisper_generator_handler_task:
            self._whisper_generator_handler_task.cancel()
        if self._transcript_generator_handler_task:
            self._transcript_generator_handler_task.cancel()
