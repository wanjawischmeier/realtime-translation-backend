import logging
import threading
import time

from libretranslatepy import LibreTranslateAPI

from io_config.logger import LOGGER
from room_manager import room_manager

class TranslationWorker(threading.Thread):
    def __init__(self, source_lang: str, target_langs=None, lt_url="http://localhost", lt_port=5000, poll_interval=1.0):
        super().__init__()
        self.source_lang = source_lang
        self.target_langs = list(target_langs) if target_langs else []
        self.lt = LibreTranslateAPI(f"http://{lt_url}:{lt_port}")
        self.poll_interval = poll_interval
        self.daemon = True
        self._stop_event = threading.Event()

    def add_target_lang(self, lang):
        if lang in self.target_langs:
            LOGGER.warning(f"Language '{lang}' is already in the target_langs list.")
            return
        self.target_langs.append(lang)
        LOGGER.info(f"Added language '{lang}' to target_langs.")

    def remove_target_lang(self, lang):
        if lang not in self.target_langs:
            LOGGER.warning(f"Language '{lang}' not found in target_langs.")
            return
        self.target_langs.remove(lang)
        LOGGER.info(f"Removed language '{lang}' from target_langs.")

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.is_set():
            cycle_start = time.time()
            try:
                to_translate = []
                
                # Check translation queues of each transcription manager until a not empty one is found
                for manager in room_manager.transcription_managers:
                    to_translate = manager.poll_sentences_to_translate()
                    if to_translate:
                        transcription_manager = manager
                        break

                if not to_translate:
                    LOGGER.warning('Translation worker thread running without any transcription managers')

                for target_lang in self.target_langs:
                    translation_results = []
                    for entry in to_translate:
                        if target_lang in entry['translated_langs']:
                            continue
                        sentence = entry['sentence']
                        try:
                            translation = self.lt.translate(sentence, source=self.source_lang, target=target_lang)
                        except Exception as e:
                            LOGGER.error(f"Translation error for '{sentence}' to '{target_lang}': {e}")
                            continue
                        translation_results.append({
                            'line_idx': entry['line_idx'],
                            'sent_idx': entry['sent_idx'],
                            'sentence': sentence,
                            'lang': target_lang,
                            'translation': translation
                        })
                    if translation_results:
                        translation_time = time.time() - cycle_start
                        transcription_manager.submit_translation(translation_results, translation_time)
                        LOGGER.info(f"Submitted {len(translation_results)} translations to '{target_lang}' in {translation_time:.2f}s.")
            except Exception as e:
                LOGGER.error(f"Error in translation cycle: {e}")

            elapsed = time.time() - cycle_start
            sleep_time = self.poll_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
