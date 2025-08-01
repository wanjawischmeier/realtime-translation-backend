import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect
from whisperlivekit import AudioProcessor

from src.transcription_manager import TranscriptionManager


class ConnectionManager:
    def __init__(self, transcription_manager:TranscriptionManager, audio_processor: AudioProcessor, whisper_generator):
        self._transcription_manager = transcription_manager
        self._audio_processor = audio_processor
        self._host: WebSocket = None
        self._clients: list[WebSocket] = []
        self.logger = logging.getLogger('ConnectionManager')
        
        self._whisper_generator_handler_task = asyncio.create_task(
            self._handle_whisper_generator(whisper_generator)
        )
        self._transcript_generator_handler_task = asyncio.create_task(
            self._handle_transcript_generator(transcription_manager.transcript_generator())
        )
        self.logger.info('Now listening for whisper and transcript generators')

    async def listen_to_host(self, websocket: WebSocket):
        if self._host:   # can't connect to multiple hosts at the same time
            await websocket.close(code=1003, reason='Multiple hosts not allowed')
            return
        
        self._host = websocket
        # self._clients.add(self._host)   # Host also wants to recieve transcript TODO: add this once host is no longer dev frontend
        self.logger.info('Host connected')

        try:
            while True:
                message = await websocket.receive_bytes()
                await self._audio_processor.process_audio(message)
        except WebSocketDisconnect:
            self._cancel_existing_tasks()
            if self._host in self._clients:
                self._clients.remove(self._host)
            self._host = None
            self.logger.info('Host disconnected')

    async def connect_client(self, websocket: WebSocket):
        await websocket.accept()
        self._clients.append(websocket)
        self.logger.info(f'Client {len(self._clients)} connected')

        try:
            while True:
                await asyncio.sleep(60)  # Just keep the connection alive
        except WebSocketDisconnect:
            self._clients.remove(websocket)
            self.logger.info(f'Client {len(self._clients) + 1} disconnected')

    async def broadcast_json(self, message: dict, broadcast_to_host=True):
        for connection in self._clients:
            await connection.send_json(message)
        
        if broadcast_to_host:
            await self._host.send_json(message)
    
    async def _handle_whisper_generator(self, whisper_generator):
        async for response in whisper_generator:
            # print(response)
            self._transcription_manager.submit_chunk(response)
            await self._host.send_json(response) # TODO: remove if host is no longer dev frontend
            
        await self._host.send_json({"type": "ready_to_stop"})
        self._whisper_generator_handler_task.cancel() # TODO: check if this is necessary/working

    async def _handle_transcript_generator(self, transcript_generator):
        async for transcript in transcript_generator:
            print('Result:')
            print(transcript)
            # await websocket.send_json(response)
            # TODO: sent to all clients
            for client in self._clients:
                client.send_json(transcript)
            
        # await websocket.send_json({'type': 'ready_to_stop'})
        self.logger.info('Results generator closed')
        self._transcript_generator_handler_task.cancel() # TODO: check if this is necessary/working

    def _cancel_existing_tasks(self):
        if self._whisper_generator_handler_task:
            self._whisper_generator_handler_task.cancel()
        if self._transcript_generator_handler_task:
            self._transcript_generator_handler_task.cancel()