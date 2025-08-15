from fastapi import WebSocket

from io_config.config import AVAILABLE_WHISPER_LANGS, CLOSE_ROOM_AFTER_SECONDS, MAX_WHISPER_INSTANCES, \
    AVAILABLE_LT_LANGS
from io_config.logger import LOGGER
from pretalx_api_wrapper.conference import conference
from room_system.room import Room


class RoomManager:
    def __init__(self):
        self.current_rooms: list[Room] = []
        self._active_room_count = 0
        self.update_rooms()

    def get_room(self, room_id: str) -> Room:
        for room in self.current_rooms:
            if room_id == room.id:
                return room
        raise RoomNotFoundError(f"Room with id {room_id} not found in room_list {[r.id for r in self.current_rooms]}")

    def update_rooms(self):
        if not conference.update_ongoing_events() and self.current_rooms != []:
            return False
        self.current_rooms.clear()
        for event in conference.ongoing_events:
            presenter = 'Unknown'
            persons = event['persons']
            if persons: # Some rooms leave this as an empty list
                presenter = persons[0]['name']
            if event['do_not_record']:
                continue
            room = Room(event['code'], event['title'], event['track'], event['room'], event['url'], event['description'],
                presenter, event['do_not_record'])
            self.current_rooms.append(room)
        return True
    
    async def activate_room_as_host(self, host: WebSocket, host_key: str, room_id:str, source_lang:str, target_lang: str, save_transcript: bool, public_transcript: bool):
        try:
            room = self.get_room(room_id)
        except RoomNotFoundError:
            await host.close(code=1003, reason=f'Room <{room_id}> not found')
            return
        
        if not source_lang in AVAILABLE_WHISPER_LANGS:
            await host.close(code=1003, reason=f'Source language {source_lang} not supported by transcription engine')
            return
        
        if not target_lang in AVAILABLE_LT_LANGS:
            await host.close(code=1003, reason=f'Target language {target_lang} not supported by translation service')
            return
        
        if room.active:
            if source_lang == room.transcription_manager.source_lang:
                # Matching configuration
                LOGGER.info(f'Host joined already active room <{room_id}> with matching configuration')
                room.cancel_deactivation()
                await room.connection_manager.ready_to_recieve_audio(host)
            else:
                # Configuration mismatch, restart room
                LOGGER.info(f'Host joined already active room <{room_id}> with mismatching configuration, restarting room...')
                room.translation_worker.subscribe_target_lang(target_lang)
                await room.restart_engine(source_lang)
        else:
            # Initial room activation
            if self._active_room_count >= MAX_WHISPER_INSTANCES:
                await host.close(code=1003, reason=f'Unable to activate room <{room_id}>: Maximum capacity of {MAX_WHISPER_INSTANCES} instances reached')
                return

            self._active_room_count += 1
            await room.activate(
                host_key, source_lang, target_lang=target_lang,
                save_transcript=save_transcript,
                public_transcript=public_transcript
            )

        LOGGER.info(f'Attempting to start listening for host in room <{room_id}>...')
        await room.connection_manager.listen_to_host(host, target_lang)

        # Host disconnected
        LOGGER.info(f'Host disconnected in room <{room_id}>, waiting a bit before closing room')
        def on_deactivate():
            self._active_room_count = max(0, self._active_room_count - 1)
        
        room.defer_deactivation(
            on_deactivate, deactivation_delay=CLOSE_ROOM_AFTER_SECONDS
        )

    async def join_room_as_client(self, client: WebSocket, room_id:str, target_lang:str):
        room = self.get_room(room_id)
        if not room:
            await client.close(code=1003, reason=f'Room <{room_id}> not found')
            return

        if not room.active:
            LOGGER.warning(f'Client connection failed: Room not active')
            await client.close(code=1003, reason='Room not active')
            return

        LOGGER.info(f'Client joining room: {room_id}')
        try:
            await room.connection_manager.connect_client(client, target_lang)
        except Exception as e:
            LOGGER.warning(f'Client connection failed:\n{e}')
            await client.close(code=1003, reason='Internal server error')
    
    async def deactivate_room(self, room_id: str) -> bool:
        room = None
        for current_room in self.current_rooms:
            if current_room.id == room_id and current_room.active:
                room = current_room
        
        if not room:
            LOGGER.info(f'No active room <{room_id}> found')
            return False
        
        LOGGER.info(f'Deactivating room <{room_id}> based on direct request')
        self._active_room_count = max(0, self._active_room_count - 1)
        await room.deactivate()
        return True

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

# ---- INITIALIZE SINGLETON ----
room_manager = RoomManager()

# ------ CUSTOM EXCEPTIONS -----
class RoomNotFoundError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)