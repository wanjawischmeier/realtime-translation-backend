import logging
import threading
import json
from intervaltree import Interval, IntervalTree

def _parse_time(timestr) -> float:
    """Convert 'HH:MM:SS' to seconds as float."""
    if not timestr:
        return None
    parts = [float(p) for p in timestr.split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 1:
        return parts[0]
    return None

class TranscriptManager:
    def __init__(self, log_path="logs/transcript_chunks.txt"):
        self.lock = threading.Lock()
        self.chunks = []  # Ordered list of transcript chunks
        self.interval_tree = IntervalTree()
        self.log_path = log_path
        self.logger = logging.getLogger("TranscriptManager")
        open(log_path, 'w').close()  # Clear log

    def update_from_lines(self, lines):
        """Update transcript with new finalized lines (from Whisper)."""
        with self.lock:
            # Remove old line/asr_buffer chunks in the same time range
            for line in lines:
                self._remove_chunks_in_range(line["beg"], line["end"], types=("line", "asr_buffer"))
                self.chunks.append({
                    "beg": line["beg"],
                    "end": line["end"],
                    "speaker": line.get("speaker"),
                    "text": line["text"],
                    "type": "line"
                })
            self._sort_and_log()

    def update_from_asr_buffer(self, buffer_chunk: dict):
        self.logger.info("ASR Update: " + json.dumps(buffer_chunk))
        with self.lock:
            status: str = buffer_chunk.get("status", None)
            lines: dict = buffer_chunk.get("lines", None)
            buffer_transcription: str = buffer_chunk.get("buffer_transcription", None)
            if status == None or lines == None or buffer_transcription == None:
                self.logger.warning("Skipped invalid asr buffer")
                return
            if status == "no_audio_detected":
                self.logger.info("Skipped empty asr buffer")
                return
            
            last_chunk_index = len(self.chunks) - 1
            if last_chunk_index >= 0 and self.chunks[last_chunk_index]["type"] == "buffer_transcription":
                self.chunks[last_chunk_index]["text"] = buffer_transcription    # update buffer_transcription chunk if it already existed
            else:
                self.chunks.append({                                            # else append it as new chunk
                    "type": "buffer_transcription",
                    "text": buffer_transcription
                })

            if len(lines) > 0:
                for i in range(len(lines)):
                    line = lines[i]
                    overlaps = self.interval_tree.overlap(line["beg"], line["end"])
                    if len(overlaps) == 0:
                        self.chunks.append()



            # If status is active but buffer is empty, keep the old buffer chunk
            # (do nothing), unless you want to clear it on silence

            self._sort_and_log()


    def update_from_translation(self, translated_sentences):
        """Update transcript with new translated sentences."""
        with self.lock:
            for t in translated_sentences:
                # Find matching line chunk by original sentence and time
                idx = self._find_chunk_by_text_and_time(t["sentence"], t["beg"], t["end"])
                if idx is not None:
                    # Replace line chunk with translation chunk
                    self.chunks[idx] = {
                        "beg": t["beg"],
                        "end": t["end"],
                        "speaker": t.get("speaker"),
                        "text": t["translation"],
                        "type": "translation",
                        "original": t["sentence"]
                    }
                else:
                    # If not found, append as new (could be a new finalized sentence)
                    self.chunks.append({
                        "beg": t["beg"],
                        "end": t["end"],
                        "speaker": t.get("speaker"),
                        "text": t["translation"],
                        "type": "translation",
                        "original": t["sentence"]
                    })
            self._sort_and_log()

    def _append_chunk(self, chunk: dict):
        self.chunks.append(chunk)
        beg: float | None = chunk.get("beg", None)
        end: float | None = chunk.get("end", None)
        
        if beg != None and end != None:
            idx = len(self.chunks) - 1
            self.interval_tree.addi(beg, end, idx)

    def _remove_chunk(self, idx):
        chunk = self.chunks.pop(idx)
        beg: float | None = chunk.get("beg", None)
        end: float | None = chunk.get("end", None)
        
        if beg != None and end != None:
            self.interval_tree.removei(beg, end, idx)


    def _remove_chunks_in_range(self, beg, end, types):
        self.chunks = [
            c for c in self.chunks
            if not (c["beg"] < end and c["end"] > beg and c["type"] in types)
        ]

    def _find_chunk_by_text_and_time(self, text, beg, end):
        for i, c in enumerate(self.chunks):
            if c["type"] == "line" and c["text"].find(text) != -1 and abs(c["beg"] - beg) < 0.1 and abs(c["end"] - end) < 0.1:
                return i
        return None

    def _sort_and_log(self):
        self.chunks.sort(key=lambda c: c["end"])
        with open(self.log_path, "w", encoding="utf-8") as f:
            for chunk in self.chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    def get_transcript(self):
        with self.lock:
            return list(self.chunks)
