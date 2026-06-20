"""
Configuration file for the Transcriber application.
Centralizes all configuration values and environment variables.
"""
import os

# API Configuration
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# File Upload Configuration
MAX_FILE_SIZE_MB = 100
MAX_CONTENT_LENGTH = MAX_FILE_SIZE_MB * 1024 * 1024

# Allowed file extensions
ALLOWED_EXTENSIONS = {
    # Video formats
    'mp4', 'avi', 'mkv', 'mov', 'webm', 'flv', 'wmv', '3gp',
    # Audio formats
    'mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg', 'wma', 'opus'
}

# Audio file extensions (for format detection)
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.wma', '.opus'}

# Output formats
SUPPORTED_OUTPUT_FORMATS = ['txt', 'srt', 'vtt', 'json']

# FFmpeg Configuration
# Audio compression settings for optimal API payload size
FFMPEG_SAMPLE_RATE = "16000"  # 16kHz - optimal for voice
FFMPEG_CHANNELS = "1"  # Mono
FFMPEG_BITRATE = "32k"  # 32kbps - compact and perfect for speech
FFMPEG_FORMAT = "mp3"

# Subprocess Timeout Configuration (in seconds)
FFMPEG_TIMEOUT = 300  # 5 minutes for video/audio processing
FFPROBE_TIMEOUT = 30  # 30 seconds for duration check
API_TIMEOUT = 180  # 3 minutes for API calls

# Gemini API Configuration
GEMINI_TEMPERATURE = 0.1  # Low temperature for deterministic transcription

# Flask Configuration
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 5000
FLASK_DEBUG = True

# Logging Configuration
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Chunking Configuration (for large files)
ENABLE_CHUNKING = True  # Enable automatic chunking for large files
CHUNK_DURATION_MINUTES = 10  # Duration of each chunk in minutes
CHUNK_THRESHOLD_MB = 100  # Auto-enable chunking for files larger than this (in MB)
