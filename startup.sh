poetry run python src/whisper_server.py --model medium -vac --buffer_trimming sentence --min-chunk-size 1 --vac-chunk-size 1 --device cuda --compute-type float16
