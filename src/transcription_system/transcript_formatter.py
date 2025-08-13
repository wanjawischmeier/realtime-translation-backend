from datetime import datetime
import os
import pickle
from typing import Any

from io_config.logger import LOGGER
from io_config.config import TRANSCRIPT_DB_DIRECTORY
from pretalx_api_wrapper import APIError
from room_system.room_manager import room_manager

def format_time(seconds: int) -> str:
    """Convert seconds to HH:MM:SS format."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def get_chunk_timestamps_from_dir(dir_path: str) -> tuple[int, int]:
    """
    Returns (first_timestamp, last_timestamp) as UNIX epoch seconds
    from all .pkl files matching the timestamp pattern in dir_path.
    If no chunks, both values are None.
    """
    timestamps = []
    for filename in os.listdir(dir_path):
        if filename.endswith('.pkl'):
            try:
                t_str = filename.replace('.pkl', '')
                dt = datetime.strptime(t_str, '%Y-%m-%d_%H-%M')
                # UNIX timestamp (integer, seconds)
                timestamps.append(int(dt.timestamp()))
            except Exception: #TODO
                continue
    if not timestamps:
        return None, None
    return min(timestamps), max(timestamps)

def get_available_transcript_directories(root_path: str) -> list[dict]:
    """
    Returns list of dicts:
      {
        "id": <directory_name>,
        "firstChunkTimestamp": <int or None>,
        "lastChunkTimestamp": <int or None>
      }
    for every immediate subdirectory in the root path.
    """
    if not os.path.exists(root_path):
        raise FileNotFoundError(f"Path does not exist: {root_path}")

    if not os.path.isdir(root_path):
        raise NotADirectoryError(f"Path is not a directory: {root_path}")

    results = []
    for name in os.listdir(root_path):
        dir_path = os.path.join(root_path, name)
        if os.path.isdir(dir_path):
            first_ts, last_ts = get_chunk_timestamps_from_dir(dir_path)
            try:
                results.append({
                    'event_data': room_manager.pretalx.get_event_by_id(name),
                    'firstChunkTimestamp': first_ts,
                    'lastChunkTimestamp': last_ts
                })
            except APIError:
                LOGGER.warning(f"Couldn't find event data for transcript with id {name}")
    return results

def get_available_transcript_list():
    return get_available_transcript_directories(TRANSCRIPT_DB_DIRECTORY)

def get_transcript_from_file(transcript_db_path: str, lang: str) -> str:
    if not os.path.exists(transcript_db_path):
        raise FileNotFoundError(f'Unable to load transcript, invalid path: {transcript_db_path}')
    
    with open(transcript_db_path, 'rb') as pkl_file:
        lines = pickle.load(pkl_file)
    return get_transcript_from_lines(lines, lang)

def get_transcript_from_lines(lines: list[dict[str, Any]], lang: str) -> str:
        """Generate a human-readable transcript string in the desired language."""
        lines_output = []
        for line in lines:
            # Only include sentences where target lang available (non-empty)
            text = " ".join(
                sentence['content'][lang]
                for sentence in line.get('sentences', [])
                if sentence['content'].get(lang)
            )
            
            if not text:
                continue
            
            # Format begin and end time
            beg_formatted = format_time(line['beg'])
            end_formatted = format_time(line['end'])
            time_range = f"{beg_formatted} - {end_formatted}"
            
            # Prepare speaker label if it is known
            speaker_label = ""
            if line.get("speaker", -1) != -1:
                speaker_label = f"{line['speaker']}: "
            
            # Combine everything for the line
            lines_output.append(f"[{speaker_label}{time_range}]\n{text}")
        
        # Join all lines into one string with newlines
        return "\n".join(lines_output)

def compile_transcript_from_dir(transcript_dir: str, lang: str) -> str:
    # List .pkl files, extracting their timestamps
    files = []
    for filename in os.listdir(transcript_dir):
        if filename.endswith('.pkl'):
            try:
                timestamp_str = filename.replace('.pkl', '')
                dt = datetime.strptime(timestamp_str, '%Y-%m-%d_%H-%M')
                files.append((dt, filename))
            except ValueError:
                # Ignore files not matching expected pattern
                continue

    # Sort files by timestamp
    files.sort()

    # Compile transcript
    compiled_chunks = []
    for dt, filename in files:
        human_time = dt.strftime("%A, %B %d, %Y at %H:%M")
        header = f"[Transcription started on {human_time}]"
        transcript_path = os.path.join(transcript_dir, filename)
        chunk = get_transcript_from_file(transcript_path, lang)
        if chunk:  # skip empty or errored chunks
            compiled_chunks.append(header)
            compiled_chunks.append(chunk)
            compiled_chunks.append("")  # Blank line between chunks

    LOGGER.info(f'Compiled transcript from {len(compiled_chunks)} chunks in {transcript_dir}')
    return "\n".join(compiled_chunks)

def compile_transcript_from_room_id(room_id: str, lang: str) -> str:
    transcript_dir = os.path.join(TRANSCRIPT_DB_DIRECTORY, room_id)
    if not os.path.isdir(transcript_dir):
        LOGGER.warning(f'Unable to compile transcript, no chunks found for room <{room_id}>')
        return
    
    return compile_transcript_from_dir(transcript_dir, lang)
    