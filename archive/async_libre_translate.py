import asyncio
from libretranslatepy import LibreTranslateAPI

class AsyncLibreTranslate:
    def __init__(self, url="http://127.0.0.1:5000"):
        self.lt = LibreTranslateAPI(url)

    async def translate(self, text, source="en", target="de"):
        # Offload the synchronous call to a thread
        return await asyncio.to_thread(self.lt.translate, text, source, target)
