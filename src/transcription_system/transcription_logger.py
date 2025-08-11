from flask import json
from io_config.logger import LOGGER
from transcription_system.transcription_helper import get_last_n_lines


def log_transcript_to_file(lines: list, incomplete_sentence: str, buffer_transcription: str, log_directory: str, log_path: str):
        with open(f'{log_directory}/n_lines_dump.json', 'w', encoding="utf-8") as f:
            f.write(json.dumps({
                'last_lines': get_last_n_lines(lines, 3),
                'incomplete_sentence': incomplete_sentence,
                'buffer_transcription': buffer_transcription
            }))

        try:
            with open(log_path, "w", encoding="utf-8") as f:
                for line_idx, line in enumerate(lines):
                    line_info = (
                        f"LINE {line_idx} | beg: {line.get('beg')} | end: {line.get('end')} | "
                        f"speaker: {line.get('speaker')}"
                    )
                    f.write(line_info + "\n")
                    for sent_idx, sentence in enumerate(line['sentences']):
                        # Write original sentence and translations
                        f.write(f"\tSENT {sent_idx}:\n")
                        for lang_code in sentence['content']:
                            f.write(f"\t\t{lang_code}: {sentence['content'][lang_code]}\n")

                # Log incomplete sentence if present
                if incomplete_sentence:
                    f.write(f"INCOMPLETE SENT: {incomplete_sentence}\n")
                # Log buffer transcription if present
                if buffer_transcription:
                    f.write(f"BUFFER: {buffer_transcription}\n")
            LOGGER.debug("Transcript updated and logged to file.")
        except FileNotFoundError as e:
            LOGGER.error(f"Failed to write transcript to {log_path}: {e}")

def log_to_translate(to_translate: list, log_path: str):
        try:
            # Prepare a JSON-serializable version
            serializable = []
            for entry in to_translate:
                # Copy entry and convert set to list
                entry_copy = dict(entry)
                entry_copy['translated_langs'] = list(entry_copy['translated_langs'])
                serializable.append(entry_copy)

            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
        except FileNotFoundError as e:
            LOGGER.error(f"Failed to write to logs/to_translate.txt: {e}")