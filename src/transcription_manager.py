import asyncio
import json
import os
import pickle
import threading
from datetime import datetime

# Initialize tokenizer
import nltk

from io_config.logger import LOGGER
from rolling_average import RollingAverage

nltk.download('punkt')
nltk.download('punkt_tab')
from nltk.tokenize import sent_tokenize

punkt_language_map = {
    'cs': 'czech',
    'da': 'danish',
    'nl': 'dutch',
    'en': 'english',
    'et': 'estonian',
    'fi': 'finnish',
    'fr': 'french',
    'de': 'german',
    'el': 'greek',
    'it': 'italian',
    'no': 'norwegian',
    'pl': 'polish',
    'pt': 'portuguese',
    'ru': 'russian',
    'sl': 'slovene',
    'es': 'spanish',
    'sv': 'swedish',
    'tr': 'turkish'
}


class TranscriptionManager:
    def __init__(self, source_lang: str, transcripts_db_directory="transcripts_db", log_directory="logs",
                 room_id="default_room", compare_depth=10, num_sentences_to_broadcast=20):
        
        if not source_lang in punkt_language_map:
            raise ValueError(f"NLTK sentence tokenizer not compatible with source_lang: {punkt_language_map}.")

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
        self._source_lang = source_lang
        self._punkt_lang = punkt_language_map.get(source_lang)
        self._num_sentences_to_broadcast = num_sentences_to_broadcast
        self._queue = asyncio.Queue()

        self.rolling_transcription_delay = RollingAverage()
        self.rolling_translation_delay = RollingAverage()

        self._buffer_transcription = "" # Any text currently in the transcription buffer
        self._incomplete_sentence = "" # Any sentence that is out of the buffer but not completed
        self._lines = []  # Each: {'beg', 'end', 'text', 'speaker', 'sentences': [ ... ]}
        self._to_translate = []  # Each: {'line_idx', 'sent_idx', 'sentence', 'translated_langs': set()}

        self.lock = threading.Lock()

    def _time_str_to_seconds(self, time_str):
        try:
            parts = list(map(int, time_str.split(':')))
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return hours * 3600 + minutes * 60 + seconds
        except TypeError as e:
            LOGGER.error(f"Error parsing time string '{time_str}': {e}")
            return 0
        
    def _format_time(self, seconds: int) -> str:
        """Convert seconds to HH:MM:SS format."""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    
    def _filter_complete_sentences(self, sentences) -> tuple[list[str], str]:
        """
        Returns a tuple:
        (list_of_complete_sentences, incomplete_sentence)
        """
        if not sentences:
            return [], ""
        last = sentences[-1].strip()
        if last and last[-1] not in ".!?":
            return sentences[:-1], last
        return sentences, ""

    def submit_chunk(self, chunk):
        with self.lock:
            # updated = self._buffer_transcription != chunk.get('buffer_transcription', '')
            updated = False # Don't update on buffer updates
            self._buffer_transcription = chunk.get('buffer_transcription', '')
            incoming_lines = chunk.get('lines', [])
            self.rolling_transcription_delay.add(chunk['remaining_time_transcription'])

            for i, line in enumerate(incoming_lines):
                beg = self._time_str_to_seconds(line['beg'])
                end = self._time_str_to_seconds(line['end'])
                text = line.get('text', '').strip()
                speaker = line.get('speaker', None)
                if text == '': continue

                # Split into sentences
                new_sentences_raw = sent_tokenize(text, language=self._punkt_lang)
                new_sentences_raw, incomplete_sentence = self._filter_complete_sentences(new_sentences_raw)
                self._incomplete_sentence = incomplete_sentence

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
                                if old_sentence_obj['sentence'] == new_sentence_text:
                                    # Sentence unchanged: keep all translations
                                    new_sentences.append(old_sentence_obj)
                                else:
                                    # Sentence changed: reset translations
                                    new_sentences.append({
                                        'sent_idx': len(new_sentences),
                                        'sentence': new_sentence_text
                                    })
                            # Step 2: Handle added sentences
                            for j in range(min_len, len(new_sentences_raw)):
                                new_sentences.append({
                                    'sent_idx': len(new_sentences),
                                    'sentence': new_sentences_raw[j]
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
                            for sent in new_sentences:
                                self._add_to_translation_queue(line_idx, sent['sent_idx'], sent['sentence'])
                            updated = True
                else:
                    # New line
                    new_sentences = []
                    for sent in new_sentences_raw:
                        new_sent = {'sentence': sent}
                        new_sentences.append(new_sent)
                    new_line = {
                        'line_idx': len(self._lines),
                        'beg': beg,
                        'end': end,
                        'text': text,
                        'speaker': speaker,
                        'sentences': new_sentences
                    }
                    self._lines.append(new_line)
                    for sent in new_sentences:
                        self._add_to_translation_queue(len(self._lines) - 1, sent['sent_idx'], sent['sentence'])
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
                    current_sentence = sent_obj['sentence']
                    if current_sentence == orig_sentence:
                        # Store translation as 'sentence_{lang}'
                        sent_obj[f'sentence_{lang}'] = translation
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
        last_n_sents = self.get_last_n_sentences()
        if broadcast and (last_n_sents or self._incomplete_sentence):
            # Put the new result in the async queue
            self._queue.put_nowait({
                'last_n_sents': last_n_sents,
                'incomplete_sentence': self._incomplete_sentence
            })

        # logging for debugging
        self._log_transcript_to_file()
        self._log_to_translate()
        transcript = self.get_human_readable_transcript("en")
        with open(f'{self.log_directory}/human_transcript.txt', 'w') as f:
            f.write(transcript)

        # write changes to disk
        with open(self._transcript_db_path, 'wb') as pkl_file:
            pickle.dump(self._lines, pkl_file)

    def poll_sentences_to_translate(self):
        with self.lock:
            # Return the list as-is
            return self._to_translate

    def get_full_transcript(self, lang=None):
        sents = []
        for line in self._lines:
            for sent in line['sentences']:
                if lang and f'sentence_{lang}' in sent:
                    sents.append(sent[f'sentence_{lang}'])
                else:
                    sents.append(sent['sentence'])
        return " ".join(sents) + " " + self._buffer_transcription

    def get_sentences(self, lang=None):
        sents = []
        for line in self._lines:
            for sent in line['sentences']:
                if lang and f'sentence_{lang}' in sent:
                    sents.append(sent[f'sentence_{lang}'])
                else:
                    sents.append(sent['sentence'])
        return sents
    
    def get_last_n_lines(self, n: int=None, include_raw_string=False):
        if not n:   # default to using configured number of lines
            n = self._num_lines_to_broadcast
        
        lines: list[dict[str, any]] = self._lines[-n:]
        
        if not include_raw_string:
            # Create copies of each dict without the 'text' entry
            lines = [
                {k: v for k, v in line.items() if k != 'text'}
                for line in lines
            ]

        return lines

    def get_last_n_sentences(self, n: int = None, include_raw_string=False):
        if not n: # # default to using configured number of sentences
            n = self._num_sentences_to_broadcast
        
        remaining = n
        result_lines = []
        
        # Process lines in reverse order to gather sentences from the end
        for line in reversed(self._lines):
            sentences = line.get('sentences', [])
            if not sentences:
                continue
            
            # Take sentences from the end of this line up to 'remaining'
            take_count = min(len(sentences), remaining)
            
            # Sentences to include from this line (take from the end)
            selected_sentences = sentences[-take_count:]
            
            # Construct a new line dictionary to preserve structure
            new_line = {
                k: v for k, v in line.items() if k != 'sentences' and (include_raw_string or k != 'text')
            }
            
            if include_raw_string:
                new_line['text'] = line.get('text', '')
            
            new_line['sentences'] = selected_sentences
            
            result_lines.append(new_line)
            
            remaining -= take_count
            if remaining <= 0:
                break
        
        # We collected lines in reverse order, reverse back for normal reading order
        result_lines.reverse()
        
        return result_lines

    def get_stats(self) -> dict:
        return {
            'transcription_delay': self.rolling_transcription_delay.get_average(),
            'translation_delay': self.rolling_translation_delay.get_average()
        }
    
    def get_human_readable_transcript(self, lang: str, transcript_db_path: str=None) -> str:
        """Generate a human readable transcript string in the desired language."""
        lines_output = []
        if transcript_db_path and os.path.exists(transcript_db_path):
            with open(transcript_db_path, 'rb') as pkl_file:
                lines = pickle.load(pkl_file)
        else:
            lines = self._lines
        
        for line in lines:
            # Format begin and end time
            beg_formatted = self._format_time(line['beg'])
            end_formatted = self._format_time(line['end'])
            time_range = f"{beg_formatted} - {end_formatted}"
            
            # Prepare speaker label if it is known
            speaker_label = ""
            if line.get("speaker", -1) != -1:
                speaker_label = f"{line['speaker']}: "
            
            # Assemble text sentences depending on lang
            if lang == self._source_lang:
                # Use original sentences unconditionally
                text = " ".join(sentence['sentence'] for sentence in line.get('sentences', []))
            else:
                # Only include translated sentences where available (non-empty)
                text = " ".join(
                    sentence[f"sentence_{lang}"]
                    for sentence in line.get('sentences', [])
                    if sentence.get(f"sentence_{lang}")
                )
            
            # Combine everything for the line
            lines_output.append(f"[{speaker_label}{time_range}]\n{text}")
        
        # Join all lines into one string with newlines
        return "\n".join(lines_output)

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

    def _log_transcript_to_file(self):
        with open(f'{self.log_directory}/n_lines_dump.json', 'w', encoding="utf-8") as f:
            f.write(json.dumps({
                'last_lines': self.get_last_n_lines(3),
                'incomplete_sentence': self._incomplete_sentence,
                'buffer_transcription': self._buffer_transcription
            }))

        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                for line_idx, line in enumerate(self._lines):
                    line_info = (
                        f"LINE {line_idx} | beg: {line.get('beg')} | end: {line.get('end')} | "
                        f"speaker: {line.get('speaker')}"
                    )
                    f.write(line_info + "\n")
                    for sent_idx, sent in enumerate(line['sentences']):
                        # Collect translations (sorted by lang code)
                        translations = []
                        for k in sorted(sent.keys()):
                            if k.startswith('sentence_') and k != 'sentence':
                                lang_code = k[len('sentence_'):]
                                translations.append((lang_code, sent[k]))
                        # Write original sentence and translations
                        if translations:
                            f.write(f"\tSENT {sent_idx}:\n")
                            f.write(f"\t\torig: {repr(sent['sentence'])}\n")
                            for lang_code, text in translations:
                                f.write(f"\t\t{lang_code}: {repr(text)}\n")
                        else:
                            # Only original sentence present, print on one line
                            f.write(f"\tSENT {sent_idx}: {repr(sent['sentence'])}\n")

                # Log incomplete sentence if present
                if hasattr(self, 'incomplete_sentence') and self._incomplete_sentence:
                    f.write(f"INCOMPLETE SENT: {self._incomplete_sentence}\n")
                # Log buffer transcription if present
                if self._buffer_transcription:
                    f.write(f"BUFFER: {self._buffer_transcription}\n")
            LOGGER.debug("Transcript updated and logged to file.")
        except FileNotFoundError as e:
            LOGGER.error(f"Failed to write transcript to {self.log_path}: {e}")
    
    def _log_to_translate(self):
        try:
            # Prepare a JSON-serializable version
            serializable = []
            for entry in self._to_translate:
                # Copy entry and convert set to list
                entry_copy = dict(entry)
                entry_copy['translated_langs'] = list(entry_copy['translated_langs'])
                serializable.append(entry_copy)

            with open(self.log_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
        except FileNotFoundError as e:
            LOGGER.error(f"Failed to write to logs/to_translate.txt: {e}")
