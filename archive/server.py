import argparse
import asyncio
import numpy as np
import sounddevice as sd
import aiohttp_cors
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack

# AudioProcessor as before
class AudioProcessor:
    def __init__(self, sample_rate, debug=False):
        self.sample_rate = sample_rate
        self.audio_queue = asyncio.Queue()
        self.stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype='float32')
        self.stream.start()
        self.running = True
        self.debug = debug
        asyncio.create_task(self.audio_feeder())

    async def audio_feeder(self):
        while self.running:
            pcm_data = await self.audio_queue.get()
            if pcm_data is None:
                break
            self.stream.write(pcm_data)

    async def feed(self, pcm_data):
        if self.debug:
            print(f"[DEBUG] Received chunk: shape={pcm_data.shape}, dtype={pcm_data.dtype}, min={pcm_data.min()}, max={pcm_data.max()}")
        await self.audio_queue.put(pcm_data)

    def close(self):
        self.running = False
        self.audio_queue.put_nowait(None)
        self.stream.stop()
        self.stream.close()

# Custom audio track handler
class AudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, track, processor):
        super().__init__()
        self.track = track
        self.processor = processor

    async def recv(self):
        frame = await self.track.recv()
        # frame is an AudioFrame (PCM16, mono or stereo)
        pcm = frame.to_ndarray().astype(np.float32) / 32768.0  # Convert to float32
        # If stereo, take mean to mono
        if pcm.ndim > 1:
            pcm = pcm.mean(axis=1)
        await self.processor.feed(pcm)
        return frame

class ServerState:
    def __init__(self):
        self.pc = None
        self.processor = None

def make_offer_handler(sample_rate, debug):
    async def offer(request):
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

        pc = RTCPeerConnection()
        processor = AudioProcessor(sample_rate=sample_rate, debug=debug)

        @pc.on("track")
        def on_track(track):
            print("Track received:", track.kind)
            if track.kind == "audio":
                local_audio = AudioTrack(track, processor)
                pc.addTrack(local_audio)

        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.json_response(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        )
    return offer

def make_terminate_handler(state):
    async def terminate(request):
        print("Received termination signal from client.")
        if state.pc:
            await state.pc.close()
            state.pc = None
        if state.processor:
            state.processor.close()
            state.processor = None
        return web.Response(text="Terminated", status=200)
    return terminate

async def health(request):
    return web.Response(text="OK", status=200)


def main():
    parser = argparse.ArgumentParser(description="aiortc audio receiver server")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--sample-rate", type=int, default=48000, help="Audio sample rate (default: 48000)")
    parser.add_argument("--debug", action="store_true", help="Enable debug output for received chunks")
    args = parser.parse_args()

    state = ServerState()
    app = web.Application()
    
    offer_resource = app.router.add_resource("/offer")
    offer_post = offer_resource.add_route("POST", make_offer_handler(args.sample_rate, args.debug))
    terminate_resource = app.router.add_resource("/terminate")
    terminate_post = terminate_resource.add_route("POST", make_terminate_handler(state))
    health_get = app.router.add_get("/health", health)

    # Enable CORS
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
        )
    })
    cors.add(offer_post)
    cors.add(terminate_post)
    cors.add(health_get)

    print(f"Starting server on port {args.port} (sample_rate={args.sample_rate}, debug={args.debug})")
    web.run_app(app, port=args.port)

if __name__ == "__main__":
    main()
