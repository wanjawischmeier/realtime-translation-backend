import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect
from whisperlivekit import AudioProcessor

from io_config.logger import LOGGER
from transcription_manager import TranscriptionManager


class ConnectionManager:
    def __init__(self, transcription_manager:TranscriptionManager, audio_processor: AudioProcessor, whisper_generator):
        self._transcription_manager = transcription_manager
        self._audio_processor = audio_processor
        self._host: WebSocket = None
        self._clients: list[WebSocket] = []
        
        self._whisper_generator_handler_task = asyncio.create_task(
            self._handle_whisper_generator(whisper_generator)
        )
        self._transcript_generator_handler_task = asyncio.create_task(
            self._handle_transcript_generator(transcription_manager.transcript_generator())
        )
        LOGGER.info('Now listening for whisper and transcript generators')

    async def listen_to_host(self, websocket: WebSocket):
        if self._host:   # can't connect to multiple hosts at the same time
            await websocket.close(code=1003, reason='Multiple hosts not allowed')
            return
        
        self._host = websocket
        self._clients.append(self._host)   # Host also wants to recieve transcript
        LOGGER.info('Host connected')

        try:
            while True:
                message = await websocket.receive_bytes()
                await self._audio_processor.process_audio(message)
        except WebSocketDisconnect:
            self._cancel_existing_tasks()
            if self._host in self._clients:
                self._clients.remove(self._host)
            self._host = None
            LOGGER.info('Host disconnected')

    async def connect_client(self, websocket: WebSocket):
        self._clients.append(websocket)
        LOGGER.info(f'Client {len(self._clients)} connected')

        try:
            while True:
                await asyncio.sleep(1)  # Just keep the connection alive TODO: check if neccessary
        except WebSocketDisconnect:
            self._clients.remove(websocket)
            LOGGER.info(f'Client {len(self._clients) + 1} disconnected') # TODO: fix recognition of client detection
    
    async def _handle_whisper_generator(self, whisper_generator):
        async for response in whisper_generator:
            self._transcription_manager.submit_chunk(response)
            
        await self._host.send_json({"type": "ready_to_stop"})
        self._whisper_generator_handler_task.cancel() # TODO: check if this is necessary/working

    async def _handle_transcript_generator(self, transcript_generator):
        async for transcript in transcript_generator:
            print('Result:')
            print(transcript)
            
            for client in self._clients:
                await client.send_json(transcript)
        
        for client in self._clients: # TODO: implement this in the frontend?
            await client.send_json({'type': 'ready_to_stop'})
        LOGGER.info('Results generator closed')
        self._transcript_generator_handler_task.cancel() # TODO: check if this is necessary/working

    def _cancel_existing_tasks(self):
        if self._whisper_generator_handler_task:
            self._whisper_generator_handler_task.cancel()
        if self._transcript_generator_handler_task:
            self._transcript_generator_handler_task.cancel()