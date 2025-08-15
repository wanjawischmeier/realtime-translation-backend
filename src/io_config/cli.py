# --- Argument Parsing ---
import sys
from argparse import ArgumentParser, Namespace
from typing import Final

def get_args() -> Namespace:
    cli = ArgumentParser(description="WhisperLiveKit + LibreTranslate FastAPI server")
    cli.add_argument("-c", "--config", default='config.yml', dest='config_file', type=str,
                     help='specify path to config file, defaults to config.yml', action='store', nargs='?')
    cli.add_argument("-m", "--model", default="medium", dest='model', help="Whisper model (tiny, small, medium, large, etc.)")
    cli.add_argument("--device", default="auto", dest='device', help="Compute device for whisper (e.g. cuda)")
    cli.add_argument("--compute-type", default="auto", dest='compute_type', help="Compute type for whisper (e.g. float32)")
    cli.add_argument("-d", "--diarization", dest='diarization', action="store_true", help="Enable speaker diarization")
    cli.add_argument("-vac", "--voice-activity-controller", dest='vac', action="store_true", help="Enable voice activity controller")
    cli.add_argument("-b", "--buffer-trimming", default='sentence', dest="buffer_trimming", help="Buffer trimming algorithm")
    cli.add_argument("--min-chunk-size", type=float, default=1, dest="min_chunk_size", help="Minimum chunk size")
    cli.add_argument("--vac-chunk-size", type=float, dest="vac_chunk_size", help="Vac chunk size")
    cli.add_argument("-log", "--log-level", default="info", dest='loglevel', type=str, help='Set the log level, defaults to info', choices=['debug', 'error'], action='store', nargs='?')
    cli.add_argument("--log-transcripts", dest='log_transcripts', action="store_true", help='Writes all ongoing transcriptions to human readable log files in /logs for debugging')
    cli.add_argument("-t", "--timeout", type=int, default=10, dest='timeout', help="Timeout in seconds for audio inactivity")
    cli.add_argument("--backlog-size", type=int, default=20, dest='backlog_size', help="Number of sentences to keep in the backlog")
    # Show help if no argument specified
    if len(sys.argv) <= 1:
        sys.argv.append('--help')
    args, unknown = cli.parse_known_args()
    return args

# These are initialized when this module is imported
ARGS: Final[Namespace] = get_args()
CONFIG_FILE: Final[str] = ARGS.config_file
MODEL: Final[str] = ARGS.model
DEVICE: Final[str] = ARGS.device
COMPUTE_TYPE: Final[str] = ARGS.compute_type
DIARIZATION: Final[bool] = ARGS.diarization
VAC: Final[bool] = ARGS.vac
BUFFER_TRIMMING: Final[str] = ARGS.buffer_trimming
MIN_CHUNK_SIZE: Final[float] = ARGS.min_chunk_size
VAC_CHUNK_SIZE: Final[float] = ARGS.vac_chunk_size
TIMEOUT: Final[int] = ARGS.timeout # TODO: were is this used? => Nowhere says PyCharm => Intention seems "Timeout in seconds for audio inactivity"
BACKLOG_SIZE: Final[int] = ARGS.backlog_size
LOGLEVEL: Final[str] = ARGS.loglevel
LOG_TRANSCRIPTS: Final[bool] = ARGS.log_transcripts

# Lightweight dev args: --model tiny
# Production args: poetry run python src/whisper_server.py --model medium -vac --buffer_trimming sentence --min-chunk-size 1 --vac-chunk-size 1 --device cuda --compute-type float32
# To download a model: poetry run whisperlivekit-server --model <model>