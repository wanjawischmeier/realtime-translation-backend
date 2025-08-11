import asyncio
from aioprocessing import AioQueue
from whisperlivekit import TranscriptionEngine, AudioProcessor

from io_config.logger import LOGGER

READY_SIGNAL = b"__READY__"  # Sentinel value for signaling readiness of audio buffer
STOP_SIGNAL = b"__STOP__"  # Sentinel value for graceful shutdown

def room_worker(room_id: str, audio_queue: AioQueue, transcript_queue: AioQueue, source_lang,
                model: str, diarization: bool, vac: bool, buffer_trimming: str,
                min_chunk_size: int, vac_chunk_size: int, device: str, compute_type: str):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    LOGGER.info(f'Loading whisper model for {room_id}: {model}, diarization={diarization}, language={source_lang}')
    engine = TranscriptionEngine(
        model=model,
        diarization=diarization,
        lan=source_lang,
        vac=vac,
        buffer_trimming=buffer_trimming,
        min_chunk_size=min_chunk_size,
        vac_chunk_size=vac_chunk_size,
        device=device,
        compute_type=compute_type
    )
    audio_processor = AudioProcessor(transcription_engine=engine)

    async def audio_feeder():
        while True:
            chunk = await audio_queue.coro_get()
            if chunk == STOP_SIGNAL:
                LOGGER.info(f'Worker process for room <{room_id}> recieved termination signal, exiting...')
                break
            await audio_processor.process_audio(chunk)

    async def whisper_feeder():
        whisper_generator = await audio_processor.create_tasks()
        async for transcript in whisper_generator:
            await transcript_queue.coro_put(transcript)
    
    async def main():
        af_task = asyncio.create_task(audio_feeder())
        wf_task = asyncio.create_task(whisper_feeder())
        LOGGER.info(f'Worker process for room <{room_id}> ready')
        await transcript_queue.coro_put(READY_SIGNAL)
        await af_task  # Wait until audio_feeder finishes (stop sentinel received)
        
        # After audio feeder ends, cancel whisper feeder to stop transcription
        wf_task.cancel()
        try:
            await wf_task
        except asyncio.CancelledError:
            pass # TODO: do something here? Gets hit somethimes, propably not a problem
        
    loop.run_until_complete(main())
    LOGGER.info(f'Worker process for room <{room_id}> stopped')
