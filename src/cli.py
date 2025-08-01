# --- Argument Parsing ---
import sys
from argparse import ArgumentParser, Namespace
from typing import Final
def get_args() -> Namespace:
    cli = ArgumentParser(description="WhisperLiveKit + LibreTranslate FastAPI server")
    cli.add_argument("-m", "--model", default="medium", dest='model', help="Whisper model (tiny, small, medium, large, etc.)")
    cli.add_argument("-d", "--diarization", dest='diarization', action="store_true", help="Enable speaker diarization")
    cli.add_argument("-h", "--host", default="0.0.0.0", dest='host', help="Host to bind FastAPI server")
    cli.add_argument("-p", "--port", type=int, default=8000, dest='port', help="Port to bind FastAPI server")
    cli.add_argument("-lth", "--libretranslate-url", dest='lt_host', default="http://127.0.0.1", help="LibreTranslate API URL")
    cli.add_argument("-ltp", "--libretranslate-port", dest='lt_port', type=int, default=5000, help="Port to bind LibreTranslate server")
    cli.add_argument("-sl", "--source-lang", default="en", dest='source_lang', help="Source language for whisper model and translation")
    cli.add_argument("-log", "--log-level", default="info", dest='loglevel', type=str, help='set the log level, defaults to info', choices=['debug', 'error'], action='store', nargs='?')
    cli.add_argument("-tl", "--target-lang", default="de", dest='target_lang', help="Target language for translation")
    cli.add_argument("-t", "--timeout", type=int, default=10, dest='timeout', help="Timeout in seconds for audio inactivity")
    # Show help if no argument specified
    if len(sys.argv) <= 1:
        sys.argv.append('--help')
    return cli.parse_args()

# These are run when this module is imported
ARGS: Final[Namespace] = get_args()
CONFIG_FILE: Final[str] = ARGS.config_file
DIARIZATION: Final[bool] = ARGS.diarization
HOST: Final[str] = ARGS.host
LOGLEVEL: Final[str] = ARGS.loglevel
LT_HOST: Final[str] = ARGS.lt_host
LT_PORT: Final[int] = ARGS.lt_port
MODEL: Final[str] = ARGS.model
PORT: Final[str] = ARGS.port
SOURCE_LANG: Final[str] = ARGS.source_lang
TARGET_LANG: Final[str] = ARGS.taget_lang
TIMEOUT: Final[int] = ARGS.timeout

