import threading
import time

from libretranslatepy import LibreTranslateAPI
from requests import RequestException

from io_config.cli import SOURCE_LANG
from io_config.config import LT_HOST, LT_PORT
from io_config.logger import LOGGER
from transcription_manager import TranscriptionManager


class TranslationWorker(threading.Thread):
    def __init__(self, transcription_manager:TranscriptionManager, poll_interval=1.0,):
        super().__init__()
        self.target_langs = []
        self.lt = LibreTranslateAPI(f"http://{LT_HOST}:{LT_PORT}")
        self.poll_interval = poll_interval
        self.daemon = True
        self.transcription_manager: TranscriptionManager = transcription_manager
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.is_set():
            cycle_start = time.time()
            try:
                # Check translation queue of transcription manager
                to_translate = self.transcription_manager.poll_sentences_to_translate()

                for target_lang in self.target_langs:
                    translation_results = []
                    for entry in to_translate:
                        if target_lang in entry['translated_langs']:
                            continue
                        sentence = entry['sentence']
                        try:
                            translation = self.lt.translate(sentence, source=SOURCE_LANG, target=target_lang)
                        except RequestException as e:
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
                        self.transcription_manager.submit_translation(translation_results, translation_time)
                        LOGGER.info(f"Submitted {len(translation_results)} translations to '{target_lang}' in {translation_time:.2f}s.")
            except Exception as e: # TODO: Remove this try/catch? I feel like its not necessary, cause the only possible error is already caught in RequestException
                LOGGER.error(f"Error in translation cycle: {e}")

            elapsed = time.time() - cycle_start
            sleep_time = self.poll_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
