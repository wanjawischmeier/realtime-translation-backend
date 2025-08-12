import threading
import time

from libretranslatepy import LibreTranslateAPI
from requests import RequestException

from io_config.config import LT_HOST, LT_PORT
from io_config.logger import LOGGER
from transcription_system.transcription_manager import TranscriptionManager


class TranslationWorker(threading.Thread):
    def __init__(self, transcription_manager: TranscriptionManager, poll_interval=1.0, target_langs: dict[str, int]={}, target_lang: str=None, max_batch_translations=4):
        super().__init__()
        self.lt = LibreTranslateAPI(f"http://{LT_HOST}:{LT_PORT}")
        self.poll_interval = poll_interval
        self.daemon = True
        self._transcription_manager: TranscriptionManager = transcription_manager
        self._stop_event = threading.Event()
        self.target_langs = target_langs
        self._max_batch_translations = max_batch_translations
        if target_lang:
            self.subscribe_target_lang(target_lang)

        LOGGER.info(f'Translation worker initialized with target langs: {self.target_langs}')
    
    def subscribe_target_lang(self, target_lang: str):
        """Increment count for subscription to a target language."""
        if target_lang == self._transcription_manager.source_lang:
            return  # don't allow source lang subscription
        
        current_count = self.target_langs.get(target_lang, 0)
        self.target_langs[target_lang] = current_count + 1
        LOGGER.info(f'Subscribed to {target_lang}, current langs: {self.target_langs}')

    def unsubscribe_target_lang(self, target_lang: str):
        """Decrement count; remove target lang if count reaches zero."""
        if target_lang not in self.target_langs:
            return

        self.target_langs[target_lang] -= 1
        
        if self.target_langs[target_lang] <= 0:
            del self.target_langs[target_lang]
        
        LOGGER.info(f'Unsubscribed from {target_lang}, current langs: {self.target_langs}')
    
    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.is_set():
            cycle_start = time.time()
            
            # Check translation queue of transcription manager
            to_translate = self._transcription_manager.poll_sentences_to_translate()

            for target_lang in self.target_langs.keys():
                translation_results = []
                for entry in to_translate:
                    if target_lang in entry['translated_langs']:
                        continue
                    sentence = entry['sentence']
                    try:
                        translation = self.lt.translate(sentence, source=self._transcription_manager.source_lang, target=target_lang)
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
                    
                    if len(translation_results) >= self._max_batch_translations:
                        # Protect against taking up too many resources with translation
                        break
                
                if translation_results:
                    translation_time = time.time() - cycle_start
                    self._transcription_manager.submit_translation(translation_results, translation_time)
                    LOGGER.info(f"Submitted {len(translation_results)} translations to '{target_lang}' in {translation_time:.2f}s.")

            elapsed = time.time() - cycle_start
            sleep_time = self.poll_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
