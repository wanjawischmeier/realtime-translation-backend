from src.sentence_buffer import split_sentences
import asyncio

async def translation_worker(sentence_buffer, websocket, lt, source_lang, target_lang):
    while True:
        untranslated = sentence_buffer.get_untranslated()
        if untranslated:
            block = " ".join(s["text"] for s in untranslated)
            print(f"[TRANSLATE] Translating block: {block}")
            translated_block = await lt.translate(block, source=source_lang, target=target_lang)
            translated_sents = split_sentences(translated_block)
            for s, t in zip(untranslated, translated_sents):
                s["translated"] = True
                s["translated_text"] = t
                print(f"[TRANSLATE] '{s['text']}' -> '{t}'")
            await websocket.send_json({
                "status": "active_translation",
                "lines": [
                    {
                        "speaker": s["speaker"],
                        "beg": s["beg"],
                        "end": s["end"],
                        "text": s["translated_text"]
                    }
                    for s in untranslated
                ]
            })
            print(f"[SEND] Sent {len(untranslated)} translated sentences to client.")
        await asyncio.sleep(0.5)