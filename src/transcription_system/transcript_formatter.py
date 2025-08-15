from datetime import datetime
import os
import pickle
from typing import Any

from io_config.logger import LOGGER
from io_config.config import TRANSCRIPT_DB_DIRECTORY
from pretalx_api_wrapper.conference import conference, EventNotFoundError

def format_time(seconds: int) -> str:
    """Convert seconds to HH:MM:SS format."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def has_access(key: str, dir: str) -> bool:
    conf_path = os.path.join(dir, 'access.conf')
    if os.path.isfile(conf_path):
        # Access is restricted to user in the file
        with open(conf_path, 'r') as conf_file:
            authorized_key = conf_file.read()
            return key == authorized_key
    
    return True

def get_available_transcript_directories(root_path: str, key: str) -> list[dict]:
    """
    Returns list of respective room infos for every immediate subdirectory in the root path.
    """
    if not os.path.exists(root_path):
        raise FileNotFoundError(f"Path does not exist: {root_path}")

    if not os.path.isdir(root_path):
        raise NotADirectoryError(f"Path is not a directory: {root_path}")

    results = []
    for room_id in os.listdir(root_path):
        room_transcript_directory = os.path.join(root_path, room_id)
        if os.path.isdir(room_transcript_directory) and os.listdir(room_transcript_directory):
            if not has_access(key, room_transcript_directory):
                continue
            try:
                results.append(conference.get_event_by_id(room_id))
            except EventNotFoundError:
                LOGGER.error(f"Couldn't find event data for transcript with id {room_id}")
    return results

def get_available_transcript_list(key: str):
    return get_available_transcript_directories(TRANSCRIPT_DB_DIRECTORY, key)

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

    if not compiled_chunks:
        LOGGER.info(f'Compiled empty transcript in {transcript_dir}')
        return

    LOGGER.info(f'Compiled transcript from {len(compiled_chunks)} chunks in {transcript_dir}')
    return "\n".join(compiled_chunks)

def compile_transcript_from_room_id(key: str, room_id: str, lang: str) -> str:
    room_directory = os.path.join(TRANSCRIPT_DB_DIRECTORY, room_id)
    if not os.path.isdir(room_directory):
        LOGGER.warning(f'Unable to compile transcript: No chunks found for room <{room_id}>')
        return 
    
    if not has_access(key, room_directory):
        LOGGER.warning(f'Unable to compile transcript: Denied access to room <{room_id}>')
        return
    
    return compile_transcript_from_dir(room_directory, lang)
    