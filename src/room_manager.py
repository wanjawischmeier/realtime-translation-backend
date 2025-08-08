import asyncio
import logging
from fastapi import WebSocket

from pretalx_api_wrapper import PretalxAPI
from room import Room
from io_config.config import AVAILABLE_WHISPER_LANGS, MAX_WHISPER_INSTANCES, AVAILABLE_LT_LANGS
from io_config.logger import LOGGER


class RoomManager:
    def __init__(self, pretalx:PretalxAPI):
        self.pretalx = pretalx
        self.current_rooms: list[Room] = []
        self._active_room_count = 0
        self._deactivation_tasks: dict[str, asyncio.Task] = {}
        self.update_rooms()

    def get_room(self, room_id: str) -> Room:
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
                
                task = self._deactivation_tasks.get(room.id, None)
                if task:
                    task.cancel() # Cancel room deactivation
                
                LOGGER.info(f'Host joined already active room <{room_id}> with matching configuration')
            else:
                # Configuration mismatch, restart room
                LOGGER.info(f'Host joined already active room <{room_id}> with mismatching configuration, restarting room...')
                await self._deactivate_room(room)
                await room.activate(source_lang, target_lang)
        else:
            # Initial room activation
            if self._active_room_count >= MAX_WHISPER_INSTANCES:
                await websocket.close(code=1003, reason=f'Unable to activate room <{room_id}>: Maximum capacity of {MAX_WHISPER_INSTANCES} instances reached')
                return

            self._active_room_count += 1
            await room.activate(source_lang, [target_lang])

        # TODO: send 'now listening' to frontend
        await room.connection_manager.listen_to_host(websocket)

        # Host disconnected
        LOGGER.info('Host disconnected, waiting a bit before closing room')
        on_deactivate = lambda: self._active_room_count = max(0, self._active_room_count - 1)
        await room.defer_deactivation(
            on_deactivate, deactivation_delay=10 # TODO: revert to 300s (5m) for production
        )

    async def join_room_as_client(self, websocket: WebSocket, room_id:str, target_lang:str):
        room = self.get_room(room_id)
        if not room:
            await websocket.close(code=1003, reason=f'Room <{room_id}> not found')
            return

        if not room.active:
            LOGGER.warning(f'Client connection failed: Room not active')
            await websocket.close(code=1003, reason='Room not active')
            return

        LOGGER.info(f'Client joining room: {room_id}')
        try:
            await room.connection_manager.connect_client(websocket)
            room.translation_worker.target_langs.append(target_lang)
            LOGGER.info(f'Added {target_lang} to {room_id}.')
        except Exception as e:
            LOGGER.warning(f'Client connection failed:\n{e}')
            await websocket.close(code=1003, reason='Internal server error')

    def get_room_list(self):
        rooms = []
        for room in self.current_rooms:
            rooms.append(room.get_data())
        
        return {
            'available_source_langs': AVAILABLE_WHISPER_LANGS,
            'available_target_langs': AVAILABLE_LT_LANGS,
            'max_active_rooms': MAX_WHISPER_INSTANCES,
            'rooms': rooms
        }


room_manager = RoomManager(pretalx=PretalxAPI())
