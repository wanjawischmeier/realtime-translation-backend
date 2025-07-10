FROM python:3.9.23-slim

# Install FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg

# Install Poetry
RUN pip install --no-cache-dir poetry

# Set workdir
WORKDIR /app

# Copy only pyproject.toml and poetry.lock for dependency installation
COPY pyproject.toml poetry.lock* ./

# Configure Poetry to not use virtualenvs (install directly to system site-packages)
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install --no-interaction --no-ansi

# Expose port 8000
EXPOSE 8000
