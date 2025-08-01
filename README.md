# Dependencies
- `sudo apt-get install ffmpeg`
- (`pyenv install 3.9.23`)
- `pyenv local 3.9.23`
- `poetry env use /home/username/.pyenv/versions/3.9.23/bin/python`

# Run using
- `ngrok start --all`

# Ngrok config:
```
endpoints:
  - name: frontend
    upstream:
      url: 5173
  - name: backend
    url: https://dynamic-freely-chigger.ngrok-free.app
    upstream:
      url: 8000
```

# Endpoints
