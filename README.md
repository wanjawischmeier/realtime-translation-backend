The backend for our [realtime translation project](https://github.com/stars/wanjawischmeier/lists/realtime-translation). Expected to be ran alongside the [frontend](https://github.com/wanjawischmeier/realtime-translation-frontend).

This project is using the [wanjawischmeier/WhisperLiveKit](https://github.com/wanjawischmeier/WhisperLiveKit) fork of [QuentinFuxa's](https://github.com/QuentinFuxa) Whisper wrapper to transcribe audio locally and in realtime. It is able to translate this transcript into a list of dynamically requested languages using [LibreTranslate](https://github.com/LibreTranslate/LibreTranslate) and send out transcript chunks to the respective frontends using a websocket connection. This pipeline is able to support multiple streamers and viewers in a room system. When streamers connect to and activate a room, they are able to send their microphone audio to the server for processing.

# Dependencies
```bash
sudo apt-get install ffmpeg
pyenv install 3.9.23 # if not installed already
pyenv local 3.9.23
poetry env use /home/username/.pyenv/versions/3.9.23/bin/python
```

# Run using
```bash
ngrok start --all # only if you want to use ngrok
bash backend.sh 
```

# Parameter explanation
```bash
-vac # Very important, should be always on
--buffer-trimming sentence # waits for sentence to be finished before processing
--buffer-trimming segment # processes after certain amount of time without waiting for context
# Segment is more stable when people speak very fast without breaks
# Sentence is a bit more accurate, but may cause lag when people speak too fast
--confidence-validation # Makes it a lot faster but slightly less accurate
--punctuation-split # Adds points between each chunk, doesnt matter if its a sentence or not
--min-chunk-size 1 # default 1, slightly lower or higher can tweak it a bit - higher leads to cut sentences, lower to more accuracy, but increases workload for GPU
--device e.g. cuda # run via cpu or gpu
--compute-type float16/float32 # float32 is more precise but takes more computing power - depends on GPU architecture
```

# Architecture
<img width="1262" height="971" alt="Unbenannt" src="https://github.com/user-attachments/assets/c92f694b-1107-4c68-8330-f94f01f3fa07" />

## Endpoints
- http://localhost:3000: Umami frontend stats
- http://localhost:8090: Beszel backend performance stats
- http://localhost:5000: LibreTranslate instance
- http://localhost:8000: FastAPI backend for http traffic
  - `GET /health`: Health check, returns [status](#health-check)
  - `GET /room_list`: Returns a [room list](#room-list)
  - `GET /vote`: Get vote list
  - `GET /vote/{id}/{action}`: Action can be `add` or `remove`
  - `POST /auth`: Checks password, returns [result](#auth-check)
  - `POST /transcript_list`: Returns a list of [transcript infos](#transcript-infos)
  - `POST /room/{room_id}/transcript/{target_lang}`: Compiles and returns the entire transcript of a given room in the `target_lang` as a string. Joins all partial transcripts available for that room.
  - `POST /room/{room_id}/close`: Closes that room, can only be performed with admin password.
- `ws://localhost:8000/room/{room_id}/{role}/{source_lang}/{target_lang}`
  - FastAPI websocket for handling streaming
  - Bidirectional
    - expects audio stream from host (`audio/webm;codecs=opus`)
    - sends all available transcriptions to host and clients in [chunks](#transcript-chunk)
  - Expects correct password in `authenticated` cookie, otherwise refuses connection
  - Parameters
    - `room_id`: unique room identifier
    - `role`: Can be `host` or `client`
    - `source_lang`/`target_lang`: The respective country codes, e.g. `de`, `en`
`en`

# Ngrok config:
```yaml
endpoints:
  - name: frontend
    upstream:
      url: 5173
  - name: backend>
    url: https://dynamic-freely-chigger.ngrok-free.app
    upstream:
      url: 8000
```

# Data structures
## Room list
```python
{
  # Languages available for transcription by the whisper engine
  "available_source_langs": [
    "de",
    "en",
    # ...
  ],

  # Languages that can be translated into by LibreTranslate
  "available_target_langs": [
    "ar",
    "az",
    # ...
  ],

  # The maximum number of rooms that can be handled by the hardware simultaniously
  "max_active_rooms": 2,

  # List of all rooms that are relevant at this point in time
  "rooms": [
    {
      # Information provided per room
      "id": "",
      "title": "",
      "description": "",
      "track": "",
      "location": "",
      "presenter": "",
      "host_connection_id": "",
      "source_lang": ""
    }
  ]
}
```

## Transcript chunk
```python
{
  "last_n_sents": [
    {
      "line_idx": 0,
      "beg": 0,
      "end": 13,
      "speaker": -1,
      "sentences": [
        {
          "sent_idx": 0,
          "content": {
            "en": "",
            "de": "",
          }
        },
        {
          "sent_idx": 1,
          "content": {
            "en": "",
            # NOTE: Not all sentences will be available in the same languages, as translation happens asynchronously
          }
        },
        {
          "sent_idx": 2,
          "content": {
            "en": "",
            "de": "",
          }
        }
      ]
    }
  ],
  "incomplete_sentence": "",
  "transcription_delay": 10.610000000000001,
  "translation_delay": 0
}
```

## Health check
```python
# If server is ready to accept requests
{"status": "ok"}

# If server is running, but not ready to accept requests
{"status": "not ready"}
```

## Auth check
```python
# If password is valid
{"status": "ok"}

# If password is invalid
{"status": "fail"}
```

## Transcript infos
```python
[
  {
    "id": "room_id_0",
    "firstChunkTimestamp": 0,
    "lastChunkTimestamp": 0
  },
  {
    "id": "room_id_1",
    "firstChunkTimestamp": 0,
    "lastChunkTimestamp": 0
  },
  # ...
]
```

# Umami
Used for tracking certain events and pageviews coming in from the frontend.

To run:
```bash
cd stats/umami
docker compose up -d
```

# Beszel
Used for tracking backend performance metrics (gpu utilization etc.)

To run:
```bash
# To start the beszel server
cd stats/beszel
docker compose up -d

# To start the agent instance for the current system
cd agent # in stats/beszel/agent
docker compose up -d
```

# TODOs
## Important
- [x] Whisper Engine an Rauminstanzen binden
- [x] Räume richtig öffnen/schließen
  - [x] Ein Raum wird geöffnet wenn der Host joint
  - [x] Ein Raum wird geschlossen, wenn der host rausgegangen ist (+ 5 minpuffer, sodass Host neu reingehen kann falls mensch nur kurz rausfliegt)
  - [x] Wenn sich die Host-Sprache ändert (erfordert neustart der engine),soll der host aus dem raum rausgehen und mit der neuen Sprache neu reingehen
  - [x] Wenn der host einem bereits offenen raum mit geänderten parametern joint, wird der raum vom room manager neu gestartet
  - [x] Send "ready" packet
- [x] Eine Restart-Option für Räume im Frontend implementieren
- [x] Websocket connects/disconnects handlen und Bugs fixen
  - [x] Unique host id
  - [x] Fix: Client disconnects dont get recognized correctly
  - [x] Fix: Rooms get prematurely closed upon host reconnects
  - [x] Preserve source lang across host reconnects
  - [x] Everyone should get kicked out of room if it closes
  - [ ] Fix host disconnect after long time
- [x] Raumliste an frontend schicken (Endpoint)
- [x] Auth cookie zum Authentifizieren nutzen
- [x] Check if room is "DO-NOT-RECORD" and prevent activating it
- [x] Use AVAILABLE_WHISPER_LANGS & AVAILABLE_LT_LANGS to verify frontend requests
- [x] Endpoint to fetch human readable transcript for room (join all partial transcripts, with date timestamp)
  - [x] Provide endpoint
  - [x] Join all partial transcripts
  - [x] Load from memory or from disk if thats not available
  - [x] Endpoint to provide list of all room id's that have transcripts stored to disk
    - Available as [transcript info](#transcript-infos) at [/transcript_list](#endpoints)
    - [x] Also store and provide room metadata alongside (@whoami)
    - [x] Respect user preferences on wether to store transcripts (@substatoo)
    - [x] Respect user preferences on wether clients can download transcripts (@substatoo)
- [x] Respect whisper instance limit when activating rooms
- [x] Whisper `device, compute_type` passthrough to cli from custom WhisperLiveKit fork
  - https://github.com/substratoo/WhisperLiveKit
- [x] Support whisper model unloading (in custom fork)
  - Propably fine, now handled by gc
- [x] Performance monitoring
  - https://beszel.dev/guide/gpu
  - (Write stats to log file? Not strictly necessary) -> Is now in umami
  - Docker compose is set up in `stats/beszel`
- [x] Umami stats
  - Docker compose is set up in `stats/umami`
- [x] Fix country coding in [transcription chunks](#transcript-chunk)
  - No longer provide default sentence, instead make a sentences `content` field a dict of country codes
- [x] Move whisper engine to seperate process
- [x] Proper target langs subscribe/unsubscribe
  - [x] Prevent doubling of target langs
  - [x] Ignore target langs that are equal to source lang (don't add to list)
- [x] Send initial transcript chunk on client connection
- [x] Move transcript and room system to seperate files in dedicated dirs
- [x] Pace translation worker (@substratoo)
  - As of now will just work through all sentences in one loop if a new language gets subscribed to
- [x] Add admin acc
  - [x] Ability to force close rooms as admin
- [ ] Help markdown file (@whoami)
- [x] Translation worker should only try to fetch the most recent n sentences (in reverse order, so most recent first)

## For potential future updates
- [ ] Fix: Ending process does not work properly some threads seems to stay running
  - Fix CTRL-C
- [ ] (Pause fetch loop when connected host is not streaming?)
- [ ] Fix: Multiple hosts not allowed error
  - Very rare, have not been able to pin it down
  - Is maybe fine for now as rooms can be restarted
- [ ] Convert pickle files for transcripts into conventional database implementation
