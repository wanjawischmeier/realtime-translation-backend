# --- Argument Parsing ---
import sys
from argparse import ArgumentParser, Namespace
from typing import Final

from whisperlivekit import TranscriptionEngine

def get_args() -> Namespace:
    cli = ArgumentParser(description="WhisperLiveKit + LibreTranslate FastAPI server")
    cli.add_argument("-c", "--config", default='config.yml', dest='config_file', type=str,
                     help='specify path to config file, defaults to config.yml', action='store', nargs='?')
    cli.add_argument("-d", "--diarization", dest='diarization', action="store_true", help="Enable speaker diarization")
    cli.add_argument("-m", "--model", default="medium", dest='model', help="Whisper model (tiny, small, medium, large, etc.)")
    cli.add_argument("-log", "--log-level", default="info", dest='loglevel', type=str, help='set the log level, defaults to info', choices=['debug', 'error'], action='store', nargs='?')
    cli.add_argument("-sl", "--source-lang", default="en", dest='source_lang', help="Source language for whisper model and translation")
    cli.add_argument("-tl", "--target-lang", default="de", dest='target_lang', help="Target language for translation")
    cli.add_argument("-t", "--timeout", type=int, default=10, dest='timeout', help="Timeout in seconds for audio inactivity")
    # Show help if no argument specified
    if len(sys.argv) <= 1:
        sys.argv.append('--help')
    args, unknown = cli.parse_known_args()
    return args

# These are initialized when this module is imported
ARGS: Final[Namespace] = get_args()
CONFIG_FILE: Final[str] = ARGS.config_file
DIARIZATION: Final[bool] = ARGS.diarization
LOGLEVEL: Final[str] = ARGS.loglevel
MODEL: Final[str] = ARGS.model
SOURCE_LANG: Final[str] = ARGS.source_lang
TARGET_LANG: Final[str] = ARGS.target_lang
TIMEOUT: Final[int] = ARGS.timeout
TRANSCRIPTION_ENGINE: Final[TranscriptionEngine]= TranscriptionEngine(model=MODEL, diarization=DIARIZATION, lan=SOURCE_LANG) # buffer_trimming="sentence"

