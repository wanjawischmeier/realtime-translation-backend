from libretranslatepy import LibreTranslateAPI
import threading
import time
import json
import logging

class TranslationWorker(threading.Thread):
    def __init__(self, sentence_buffer, source_lang="en", target_lang="de", lt_url="http://127.0.0.1:5000", log_path="logs/committed_translations.txt", poll_interval=0.5):
        super().__init__(daemon=True)
        self.sentence_buffer = sentence_buffer
        self.log_path = log_path
        self.poll_interval = poll_interval
        self.translated_sentences = []
        self.last_translated_index = 0
        self.running = True
        self.translator = LibreTranslateAPI(lt_url)
        self.source_lang = source_lang
        self.target_lang = target_lang

        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
        self.logger = logging.getLogger("TranslationWorker")
        open(log_path, 'w').close() # Clear log file

    def run(self):
        while self.running:
            with self.sentence_buffer.lock:
                committed = self.sentence_buffer.committed_sentences
                # Find the first difference (rollback or correction)
                rollback_index = None
                for i in range(min(self.last_translated_index, len(committed))):
                    if committed[i]["sentence"] != self.translated_sentences[i]["sentence"]:
                        rollback_index = i
                        break
                if rollback_index is None:
                    rollback_index = min(self.last_translated_index, len(committed))
                # If rollback or correction detected
                if rollback_index < self.last_translated_index:
                    self.logger.info(f"Rollback detected in translation worker to index {rollback_index}")
                    self.last_translated_index = rollback_index
                    self.translated_sentences = self.translated_sentences[:rollback_index]
                    self._log_rollback(rollback_index)
                # Translate new, finalized sentences
                for i in range(self.last_translated_index, len(committed)):
                    # Only translate if sentence appears "complete"
                    sentence = committed[i]["sentence"]
                    if not sentence or sentence[-1] not in ".!?":  # Heuristic for completeness
                        break  # Don't translate incomplete sentence at the end
                    meta = {k: v for k, v in committed[i].items() if k != "sentence"}
                    try:
                        translation = self.translator.translate(sentence, self.source_lang, self.target_lang)
                    except Exception as e:
                        self.logger.error(f"Translation failed: {e}")
                        translation = ""
                    self._log_translation(sentence, translation, meta)
                    self.logger.info(f"Translated: {sentence} -> {translation}")
                    self.translated_sentences.append({"sentence": sentence, "translation": translation, **meta})
                    self.last_translated_index += 1
            time.sleep(self.poll_interval)

    def _log_translation(self, src, translation, meta):
        entry = {"event": "commit", "source": src, "translation": translation, **meta}
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _log_rollback(self, index):
        entry = {"event": "rollback", "rollback_to_index": index}
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def stop(self):
        self.running = False
