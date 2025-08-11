from io_config.logger import LOGGER


def time_str_to_seconds(time_str):
    try:
        parts = list(map(int, time_str.split(':')))
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return hours * 3600 + minutes * 60 + seconds
    except TypeError as e:
        LOGGER.error(f"Error parsing time string '{time_str}': {e}")
        return 0

def filter_complete_sentences(sentences) -> tuple[list[str], str]:
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

def get_last_n_lines(lines: list, n: int, include_raw_string=False):
    lines: list[dict[str, any]] = lines[-n:]
        
    if not include_raw_string:
        # Create copies of each dict without the 'text' entry
        lines = [
            {k: v for k, v in line.items() if k != 'text'}
            for line in lines
        ]

    return lines

def get_last_n_sentences(lines: list, n: int, include_raw_string=False):
    remaining = n
    result_lines = []
        
    # Process lines in reverse order to gather sentences from the end
    for line in reversed(lines):
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