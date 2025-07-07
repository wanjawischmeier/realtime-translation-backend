import re

def split_sentences(text):
    # Splits text into sentences using punctuation as delimiters
    sentence_endings = re.compile(r'([.!?])')
    sentences = []
    current = ''
    for part in sentence_endings.split(text):
        current += part
        if sentence_endings.match(part):
            sentences.append(current.strip())
            current = ''
    if current.strip():
        sentences.append(current.strip())
    return sentences

class SentenceBuffer:
    def __init__(self):
        self.sentences = []
        self.current_lines = {}  # speaker -> current line dict
        self.finalized_begs = set()  # (speaker, beg)

    def add_lines(self, lines):
        for line in lines:
            speaker = line["speaker"]
            beg = line["beg"]
            # If this is a new line for this speaker, finalize the previous one
            if speaker in self.current_lines:
                prev_line = self.current_lines[speaker]
                prev_beg = prev_line["beg"]
                if prev_beg != beg and (speaker, prev_beg) not in self.finalized_begs:
                    self._finalize_line(prev_line)
                    self.finalized_begs.add((speaker, prev_beg))
            self.current_lines[speaker] = line

    def _finalize_line(self, line):
        for sent in split_sentences(line["text"]):
            if sent.strip():
                key = (line["speaker"], line["beg"], sent)
                if not any(s["speaker"] == line["speaker"] and s["beg"] == line["beg"] and s["text"] == sent for s in self.sentences):
                    self.sentences.append({
                        "speaker": line["speaker"],
                        "beg": line["beg"],
                        "end": line["end"],
                        "text": sent,
                        "translated": False
                    })
                    print(f"[BUFFER] Finalized sentence: '{sent}' (speaker {line['speaker']}, {line['beg']}–{line['end']})")

    def finalize_all(self):
        for speaker, line in self.current_lines.items():
            beg = line["beg"]
            if (speaker, beg) not in self.finalized_begs:
                self._finalize_line(line)
                self.finalized_begs.add((speaker, beg))
        self.current_lines = {}

    def get_untranslated(self):
        untranslated = [s for s in self.sentences if not s["translated"]]
        if untranslated:
            print(f"[BUFFER] {len(untranslated)} untranslated sentences ready for translation.")
        return untranslated
