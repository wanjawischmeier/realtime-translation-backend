import asyncio
import os
import pickle
import threading
from datetime import datetime

from io_config.cli import LOG_TRANSCRIPTS
from io_config.logger import LOGGER
from rolling_average import RollingAverage
from transcription_system.transcription_helper import filter_complete_sentences, get_last_n_sentences, time_str_to_seconds
from transcription_system.transcription_logger import log_transcript_to_file, log_to_translate
from transcription_system.sentence_tokenizer import punkt_language_map, sent_tokenize



class TranscriptionManager:
    def __init__(self, room_id, source_lang: str, transcripts_db_directory="transcripts_db", log_directory="logs", compare_depth=10, num_sentences_to_broadcast=20,
                 save_transcript: bool=False):
        
        self.save_transcript = save_transcript
        if not source_lang in punkt_language_map:
            raise ValueError(f"NLTK sentence tokenizer not compatible with source_lang: {punkt_language_map}.")

        if save_transcript:
            transcripts_db_directory = f"{transcripts_db_directory}/{room_id}"
            if not os.path.exists(transcripts_db_directory):
                os.makedirs(transcripts_db_directory)
            if not os.path.exists(log_directory):
                os.mkdir(log_directory)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        self._transcript_db_path = f"{transcripts_db_directory}/{timestamp}.pkl"
        self.log_directory = log_directory
        self.room_id = room_id
        self.log_path = f'{log_directory}/to_translate_{self.room_id}.txt'
        self.compare_depth = compare_depth
        self.source_lang = source_lang
        self._punkt_lang = punkt_language_map.get(source_lang)
        self._num_sentences_to_broadcast = num_sentences_to_broadcast
        self.last_transcript_chunk = {
            'last_n_sents': [],
            'incomplete_sentence': '',
            'transcription_delay': 0,
            'translation_delay': 0
        }
        self._queue = asyncio.Queue()

        self.rolling_transcription_delay = RollingAverage(n=4)
        self.rolling_translation_delay = RollingAverage(n=4)

        self._buffer_transcription = "" # Any text currently in the transcription buffer
        self._incomplete_sentence = "" # Any sentence that is out of the buffer but not completed
        self._lines = []  # Each: {'beg', 'end', 'text', 'speaker', 'sentences': [ ... ]}
        self._to_translate = []  # Each: {'line_idx', 'sent_idx', 'sentence', 'translated_langs': set()}

        self.lock = threading.Lock()

    

    def submit_chunk(self, chunk):
        with self.lock:
            # updated = self._buffer_transcription != chunk.get('buffer_transcription', '')
            updated = False # Don't update on buffer updates
            self._buffer_transcription = chunk.get('buffer_transcription', '')
            incoming_lines = chunk.get('lines', [])
            self.rolling_transcription_delay.add(chunk['remaining_time_transcription'])

            for i, line in enumerate(incoming_lines):
                beg = time_str_to_seconds(line['beg'])
                end = time_str_to_seconds(line['end'])
                text = line.get('text', '').strip()
                speaker = line.get('speaker', None)
                if text == '': continue

                # Split into sentences
                new_sentences_raw = sent_tokenize(text, language=self._punkt_lang)
                new_sentences_raw, incomplete_sentence = filter_complete_sentences(new_sentences_raw)
                if i == len(incoming_lines) - 1 and incomplete_sentence != self._incomplete_sentence:
                    self._incomplete_sentence = incomplete_sentence
                    updated = True

                # TODO: Move parsing logic into sepeperate function
                line_idx = len(self._lines) - len(incoming_lines) + i
                if 0 <= line_idx < len(self._lines):
                    if line_idx >= len(self._lines) - self.compare_depth:
                        if text != self._lines[line_idx]['text']:
                            # Line has changed, compare old and new sentences
                            old_sentences = self._lines[line_idx]['sentences']

                            # Prepare new sentences list
                            new_sentences = []
                            min_len = min(len(old_sentences), len(new_sentences_raw))
                            # Step 1: Update unchanged sentences, reset changed ones
                            for j in range(min_len):
                                old_sentence_obj = old_sentences[j]
                                new_sentence_text = new_sentences_raw[j]
                                if old_sentence_obj['content'][self.source_lang] == new_sentence_text:
                                    # Sentence unchanged: keep all translations
                                    new_sentences.append(old_sentence_obj)
                                else:
                                    # Sentence changed: reset translations
                                    new_sentences.append({
                                        'sent_idx': len(new_sentences),
                                        'content': {
                                            self.source_lang: new_sentence_text
                                        }
                                    })
                            # Step 2: Handle added sentences
                            for j in range(min_len, len(new_sentences_raw)):
                                new_sentences.append({
                                    'sent_idx': len(new_sentences),
                                    'content': {
                                        self.source_lang: new_sentences_raw[j]
                                    }
                                })

                            # Update the line
                            self._lines[line_idx].update({
                                'line_idx': line_idx,
                                'beg': beg,
                                'end': end,
                                'text': text,
                                'speaker': speaker,
                                'sentences': new_sentences
                            })

                            # Update _to_translate for each sentence
                            for sentence in new_sentences:
                                self._add_to_translation_queue(
                                    line_idx,
                                    sentence['sent_idx'],
                                    sentence['content'][self.source_lang]
                                )
                            updated = True
                else:
                    # New line
                    new_sentences = []
                    for i, sentence in enumerate(new_sentences_raw):
                        new_sentences.append({
                            'sent_idx': i,
                            'content': {
                                self.source_lang: sentence
                            }
                        })
                    new_line = {
                        'line_idx': len(self._lines),
                        'beg': beg,
                        'end': end,
                        'text': text,
                        'speaker': speaker,
                        'sentences': new_sentences
                    }
                    self._lines.append(new_line)
                    for sentence in new_sentences:
                        self._add_to_translation_queue(
                            len(self._lines) - 1,
                            sentence['sent_idx'],
                            sentence['content'][self.source_lang]
                        )
                    updated = True

            if updated: # only push if changes occured
                self._push_updated_transcript()

    def submit_translation(self, translation_results, translation_time):
        """
        translation_results: list of dicts, each like
            {
                'line_idx': ...,
                'sent_idx': ...,
                'sentence': ...,      # original sentence (for checking)
                'lang': 'en',         # language code
                'translation': ...    # translated sentence
            }
        """
        with self.lock:
            self.rolling_translation_delay.add(translation_time / len(translation_results))

            for result in translation_results:
                line_idx = result['line_idx']
                sent_idx = result['sent_idx']
                orig_sentence = result['sentence']
                lang = result['lang']
                translation = result['translation']

                try:
                    line = self._lines[line_idx]
                    sent_obj = line['sentences'][sent_idx]
                    current_sentence = sent_obj['content'][self.source_lang]
                    if current_sentence == orig_sentence:
                        # Store translation as 'content: {lang: "..."}'
                        sent_obj['content'][lang] = translation
                        # Update _to_translate entry for this sentence
                        for entry in self._to_translate:
                            if (entry['line_idx'] == line_idx and
                                entry['sent_idx'] == sent_idx and
                                entry['sentence'] == orig_sentence):
                                entry['translated_langs'].add(lang)
                                break
                    else:
                        LOGGER.warning(
                            f"Discarded translation: sentence changed at line {line_idx}, sent {sent_idx}."
                            f" Old: '{orig_sentence}' New: '{current_sentence}'"
                        )
                except IndexError:
                    LOGGER.warning(
                        f"Discarded translation: line_idx {line_idx} or sent_idx {sent_idx} out of range."
                    )

            self._push_updated_transcript()

    async def transcript_generator(self):
        while True:
            # Wait for the next result from the queue asynchronously
            result = await self._queue.get()

            # Optionally handle shutdown or sentinel value signaling completion
            if result is None:
                break

            yield result
        
        LOGGER.info('Transcript generator terminated')
    
    def _push_updated_transcript(self, broadcast=True):
        # send last n lines of updated transcript to all connected clients
        last_n_sents = get_last_n_sentences(self._lines, self._num_sentences_to_broadcast)
        self.last_transcript_chunk = {
            'last_n_sents': last_n_sents,
            'incomplete_sentence': self._incomplete_sentence,
            'transcription_delay': self.rolling_transcription_delay.get_average(),
            'translation_delay': self.rolling_translation_delay.get_average()
        }
        if broadcast and (last_n_sents or self._incomplete_sentence):
            # Put the new result in the async queue
            self._queue.put_nowait(self.last_transcript_chunk)

        # logging for debugging
        if LOG_TRANSCRIPTS:
            log_transcript_to_file(
                self._lines,
                self._incomplete_sentence,
                self._buffer_transcription,
                self.log_directory,
                self.log_path
            )
            log_to_translate(self._to_translate, self.log_path)

        # write changes to disk
        if self.save_transcript:
            with open(self._transcript_db_path, 'wb') as pkl_file:
                pickle.dump(self._lines, pkl_file)

    def poll_sentences_to_translate(self):
        with self.lock:
            # Return the list as-is
            return self._to_translate

    def _add_to_translation_queue(self, line_idx, sent_idx, sentence):
        # Find existing entry for this (line_idx, sent_idx)
        for entry in self._to_translate:
            if entry['line_idx'] == line_idx and entry['sent_idx'] == sent_idx:
                if entry['sentence'] == sentence:
                    # Sentence unchanged, nothing to do
                    return
                else:
                    # Sentence changed, update text and reset translations
                    entry['sentence'] = sentence
                    entry['translated_langs'] = set()
                    LOGGER.debug(f"Changed sentence: at line {line_idx}, sent {sent_idx}, text: {sentence}")
                    return
        # No entry found, add new
        self._to_translate.append({
            'line_idx': line_idx,
            'sent_idx': sent_idx,
            'sentence': sentence,
            'translated_langs': set()
        })
