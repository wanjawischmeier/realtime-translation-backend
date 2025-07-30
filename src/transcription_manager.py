import threading
import logging
import json
import os
from rolling_average import RollingAverage

# Initialize tokenizer
import nltk
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
    def __init__(self, source_lang, log_path="logs/transcript.txt", compare_depth=10):
        if not source_lang in punkt_language_map:
            raise ValueError(f"NLTK sentence tokenizer not compatible with source_lang: {punkt_language_map}.")

        if not os.path.exists("logs"):
            os.mkdir("logs")
        self.logger = logging.getLogger("TranscriptionManager")
        self.log_path = log_path
        self.compare_depth = compare_depth
        self.source_lang = source_lang
        self._punkt_lang = punkt_language_map.get(source_lang)

        self.rolling_transcription_delay = RollingAverage()
        self.rolling_translation_delay = RollingAverage()

        self.buffer_transcription = "" # Any text currently in the transcription buffer
        self.incomplete_sentence = "" # Any sentence that is out of the buffer but not completed
        self.lines = []  # Each: {'beg', 'end', 'text', 'speaker', 'sentences': [ ... ]}
        self._to_translate = []  # Each: {'line_idx', 'sent_idx', 'sentence', 'translated_langs': set()}

        self.lock = threading.Lock()

    def _time_str_to_seconds(self, time_str):
        try:
            parts = list(map(int, time_str.split(':')))
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return hours * 3600 + minutes * 60 + seconds
            else:
                self.logger.error(f"Unexpected time format: {time_str}")
                return 0
        except Exception as e:
            self.logger.error(f"Error parsing time string '{time_str}': {e}")
            return 0
    
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
            updated = self.buffer_transcription != chunk.get('buffer_transcription', '')
            self.buffer_transcription = chunk.get('buffer_transcription', '')
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
                self.incomplete_sentence = incomplete_sentence

                line_idx = len(self.lines) - len(incoming_lines) + i
                if 0 <= line_idx < len(self.lines):
                    if line_idx >= len(self.lines) - self.compare_depth:
                        if text != self.lines[line_idx]['text']:
                            # Line has changed, compare old and new sentences
                            old_sentences = self.lines[line_idx]['sentences']

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
                                    new_sentences.append({'sentence': new_sentence_text})
                            # Step 2: Handle added sentences
                            for j in range(min_len, len(new_sentences_raw)):
                                new_sentences.append({'sentence': new_sentences_raw[j]})

                            # Update the line
                            self.lines[line_idx].update({
                                'beg': beg,
                                'end': end,
                                'text': text,
                                'speaker': speaker,
                                'sentences': new_sentences
                            })

                            # Update _to_translate for each sentence
                            for j, sent in enumerate(new_sentences):
                                self._add_to_translation_queue(line_idx, j, sent['sentence'])
                            updated = True
                else:
                    # New line
                    new_sentences = []
                    for sent in new_sentences_raw:
                        new_sent = {'sentence': sent}
                        new_sentences.append(new_sent)
                    new_line = {
                        'beg': beg,
                        'end': end,
                        'text': text,
                        'speaker': speaker,
                        'sentences': new_sentences
                    }
                    self.lines.append(new_line)
                    for j, sent in enumerate(new_sentences):
                        self._add_to_translation_queue(len(self.lines) - 1, j, sent['sentence'])
                    updated = True

            if updated:
                self._log_transcript_to_file()
                self._log_to_translate()

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
                    line = self.lines[line_idx]
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
                        self.logger.warning(
                            f"Discarded translation: sentence changed at line {line_idx}, sent {sent_idx}."
                            f" Old: '{orig_sentence}' New: '{current_sentence}'"
                        )
                except IndexError:
                    self.logger.warning(
                        f"Discarded translation: line_idx {line_idx} or sent_idx {sent_idx} out of range."
                    )

            self._log_transcript_to_file()
            self._log_to_translate()
    
    def poll_sentences_to_translate(self):
        with self.lock:
            # Return the list as-is
            return self._to_translate

    def get_full_transcript(self, lang=None):
        sents = []
        for line in self.lines:
            for sent in line['sentences']:
                if lang and f'sentence_{lang}' in sent:
                    sents.append(sent[f'sentence_{lang}'])
                else:
                    sents.append(sent['sentence'])
        return " ".join(sents) + " " + self.buffer_transcription

    def get_sentences(self, lang=None):
        sents = []
        for line in self.lines:
            for sent in line['sentences']:
                if lang and f'sentence_{lang}' in sent:
                    sents.append(sent[f'sentence_{lang}'])
                else:
                    sents.append(sent['sentence'])
        return sents

    def get_stats(self) -> dict:
        return {
            'transcription_delay': self.rolling_transcription_delay.get_average(),
            'translation_delay': self.rolling_translation_delay.get_average()
        }

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
                    self.logger.debug(f"Changed sentence: at line {line_idx}, sent {sent_idx}, text: {sentence}")
                    return
        # No entry found, add new
        self._to_translate.append({
            'line_idx': line_idx,
            'sent_idx': sent_idx,
            'sentence': sentence,
            'translated_langs': set()
        })

    def _log_transcript_to_file(self):
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                for line_idx, line in enumerate(self.lines):
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
                if hasattr(self, 'incomplete_sentence') and self.incomplete_sentence:
                    f.write(f"INCOMPLETE SENT: {self.incomplete_sentence}\n")
                # Log buffer transcription if present
                if self.buffer_transcription:
                    f.write(f"BUFFER: {self.buffer_transcription}\n")
            self.logger.debug("Transcript updated and logged to file.")
        except Exception as e:
            self.logger.error(f"Failed to write transcript to {self.log_path}: {e}")
    
    def _log_to_translate(self):
        try:
            # Prepare a JSON-serializable version
            serializable = []
            for entry in self._to_translate:
                # Copy entry and convert set to list
                entry_copy = dict(entry)
                entry_copy['translated_langs'] = list(entry_copy['translated_langs'])
                serializable.append(entry_copy)

            with open("logs/to_translate.txt", "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to write to logs/to_translate.txt: {e}")