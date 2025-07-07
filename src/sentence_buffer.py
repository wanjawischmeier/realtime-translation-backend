import threading
import json
import logging
import re

def split_sentences(text):
    # Basic sentence splitter (improve as needed)
    # Handles ., !, ? followed by space or end of string
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]

class SentenceBuffer:
    def __init__(self, log_path="logs/committed_sentences.txt", rewrite_on_rollback=True):
        self.lock = threading.Lock()
        self.committed_sentences = []  # List of dicts: {"sentence", "speaker", "beg", "end", ...}
        self.log_path = log_path
        self.rewrite_on_rollback = rewrite_on_rollback

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s"
        )
        self.logger = logging.getLogger("SentenceBuffer")
        open(log_path, 'w').close() # Clear log file

    def process(self, lines):
        """
        Process the latest lines from Whisper.
        Commit new, finalized sentences. Rollback if corrections detected.
        """
        with self.lock:
            # Flatten all lines into a list of sentences with metadata
            new_sentences = []
            for line in lines:
                # Split line into sentences
                sents = split_sentences(line["text"])
                for sent in sents:
                    # Attach metadata from the line to each sentence
                    new_sentences.append({
                        "sentence": sent,
                        "speaker": line.get("speaker"),
                        "beg": line.get("beg"),
                        "end": line.get("end"),
                        "diff": line.get("diff"),
                    })

            # Find the first index where committed and new sentences differ
            rollback_index = None
            for i, (comm, new) in enumerate(zip(self.committed_sentences, new_sentences)):
                if comm["sentence"] != new["sentence"]:
                    rollback_index = i
                    break
            if rollback_index is None:
                rollback_index = min(len(self.committed_sentences), len(new_sentences))

            # If rollback is needed
            if rollback_index < len(self.committed_sentences):
                self.logger.info(f"Rollback to sentence index {rollback_index}")
                self.committed_sentences = self.committed_sentences[:rollback_index]
                if self.rewrite_on_rollback:
                    self._rewrite_log()
                self._log_rollback(rollback_index)

            # Commit new sentences
            for i in range(rollback_index, len(new_sentences)):
                self.committed_sentences.append(new_sentences[i])
                self._log_sentence(new_sentences[i])
                self.logger.info(f"Committed new sentence: {new_sentences[i]['sentence']}")

    def _log_sentence(self, sentence_dict):
        """Write the sentence as JSON to the log file."""
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "commit", **sentence_dict}, ensure_ascii=False) + "\n")

    def _log_rollback(self, index):
        """Write a rollback event to the log file."""
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "rollback", "rollback_to_index": index}, ensure_ascii=False) + "\n")

    def _rewrite_log(self):
        """Rewrite the log file to reflect only the current committed sentences."""
        with open(self.log_path, "w", encoding="utf-8") as f:
            for sent in self.committed_sentences:
                f.write(json.dumps({"event": "commit", **sent}, ensure_ascii=False) + "\n")

    def get_committed(self):
        with self.lock:
            return list(self.committed_sentences)
