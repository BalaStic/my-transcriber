# 🎙️ Gemini Transcriber

A powerful, fast, and secure audio/video transcription application powered by Google's Gemini 2.5 Flash API and FFmpeg. Features both a modern web interface and a command-line interface for flexible transcription workflows.

## ✨ Features

- **Multi-Format Support**: Transcribe video (MP4, AVI, MKV, MOV, WebM, etc.) and audio files (MP3, WAV, AAC, FLAC, etc.)
- **Multiple Output Formats**: Generate transcriptions as plain text (TXT), SubRip subtitles (SRT), WebVTT, or structured JSON
- **Smart Audio Compression**: Automatically extracts and compresses audio to 16kHz mono MP3 for optimal API performance
- **Modern Web UI**: Drag-and-drop interface with real-time progress tracking
- **CLI Tool**: Command-line interface for batch processing and automation
- **Large File Support**: Automatic chunking for files over 100MB - handle videos of any size!
- **Custom Prompts**: Add context-specific instructions to improve transcription accuracy
- **Secure**: Implements security best practices including proper temp file handling, input validation, and structured logging

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+**
- **FFmpeg**: Required for audio/video processing
  - Windows: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt-get install ffmpeg` or `sudo yum install ffmpeg`
- **Gemini API Key**: Get yours from [Google AI Studio](https://makersuite.google.com/app/apikey)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/my-transcriber.git
   cd my-transcriber
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up your API key**:
   ```bash
   # On Windows (Command Prompt)
   set GEMINI_API_KEY=your_api_key_here
   
   # On Windows (PowerShell)
   $env:GEMINI_API_KEY="your_api_key_here"
   
   # On macOS/Linux
   export GEMINI_API_KEY=your_api_key_here
   ```

## 📖 Usage

### Web Interface

1. **Start the Flask server**:
   ```bash
   python app.py
   ```

2. **Open your browser** to `http://localhost:5000`

3. **Upload and transcribe**:
   - Drag and drop a video or audio file
   - Select your desired output format (TXT, SRT, VTT, or JSON)
   - Optionally add custom guidelines
   - Click "Start Transcription"
   - Download or copy your results!

### Command-Line Interface

```bash
python transcribe.py -i input_video.mp4 -f srt
```

**Options**:
- `-i, --input`: Path to input video or audio file (required)
- `-o, --output`: Path to save transcription (default: same name as input with new extension)
- `-f, --format`: Output format - txt, srt, vtt, or json (default: txt)
- `--prompt`: Additional instructions for the transcription

**Examples**:

```bash
# Basic transcription to text
python transcribe.py -i lecture.mp4

# Generate SRT subtitles
python transcribe.py -i video.mp4 -f srt -o subtitles.srt

# Transcribe with custom context
python transcribe.py -i medical_talk.mp3 -f txt --prompt "This is a medical lecture. Handle terms like 'myocardial infarction' carefully."

# Generate structured JSON output
python transcribe.py -i interview.wav -f json

# Process large file with chunking (auto-enabled for files >100MB)
python transcribe.py -i large_video.mp4 -f srt

# Force enable chunking for smaller files
python transcribe.py -i video.mp4 -f txt --enable-chunking

# Customize chunk duration (default: 10 minutes)
python transcribe.py -i long_lecture.mp4 -f srt --chunk-duration 15

# Disable chunking (process as single file)
python transcribe.py -i video.mp4 -f txt --disable-chunking
```

## 📦 Large File Support (Chunking)

The transcriber automatically handles large video files (>100MB) through intelligent chunking:

### How It Works

1. **Automatic Detection**: Files larger than 100MB automatically trigger chunking mode
2. **Smart Splitting**: Video is split into time-based chunks (default: 10 minutes each)
3. **Individual Processing**: Each chunk is transcribed separately
4. **Intelligent Merging**: Results are merged with proper timestamp adjustments
5. **Cleanup**: All temporary chunk files are automatically removed

### Chunking Options

**CLI Arguments**:
- `--enable-chunking`: Force enable chunking regardless of file size
- `--disable-chunking`: Disable chunking and process as single file
- `--chunk-duration N`: Set chunk duration in minutes (default: 10)
- `--chunk-threshold N`: Set file size threshold in MB for auto-chunking (default: 100)

**Configuration** (`config.py`):
```python
ENABLE_CHUNKING = True          # Enable/disable chunking globally
CHUNK_DURATION_MINUTES = 10     # Default chunk duration
CHUNK_THRESHOLD_MB = 100        # Auto-chunk files larger than this
```

### Format-Specific Merging

Each output format is handled intelligently:

- **TXT**: Chunks concatenated with paragraph breaks
- **SRT**: Subtitles renumbered, timestamps adjusted for continuity
- **VTT**: Cues merged with proper timestamp offsets
- **JSON**: Segments combined with adjusted timestamps

### Example: Processing a 2GB Video

```bash
python transcribe.py -i large_movie.mp4 -f srt

# Output:
# File size: 2048.00 MB
# ⚠️  Large file detected (2048.00MB)
# ⚠️  Enabling chunked processing mode
# ⚠️  Chunk duration: 10 minutes
# 
# ============================================================
# CHUNKED PROCESSING MODE
# ============================================================
# ✓ Video split into 12 chunks
#
# [1/12] Processing chunk: large_movie_chunk_000.mp4
#     Duration: 10:00
#     ✓ Chunk 1 transcribed successfully
# [2/12] Processing chunk: large_movie_chunk_001.mp4
#     ...
# ✓ Results merged successfully
# ✓ Temporary chunks removed
```

### Benefits

✅ **No file size limits**: Process videos of any size
✅ **Better memory management**: Only one chunk in memory at a time
✅ **Resilience**: If one chunk fails, others still succeed
✅ **Progress tracking**: See exactly which chunk is being processed
✅ **Automatic cleanup**: No manual file management needed

## ⚙️ Configuration

The application can be configured via `config.py`:

- **File size limits**: Adjust `MAX_FILE_SIZE_MB`
- **Supported formats**: Modify `ALLOWED_EXTENSIONS`
- **FFmpeg settings**: Tune audio compression parameters
- **API timeouts**: Configure timeout values for long files
- **Logging levels**: Set via `LOG_LEVEL` environment variable

### Environment Variables

- `GEMINI_API_KEY`: Your Gemini API key (required)
- `LOG_LEVEL`: Logging verbosity - DEBUG, INFO, WARNING, ERROR (default: INFO)

## 🏗️ Architecture

```
my-transcriber/
├── app.py              # Flask web application
├── transcribe.py       # CLI tool
├── transcriber.py      # Core transcription logic
├── config.py           # Centralized configuration
├── logger.py           # Logging setup
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Web UI
└── README.md           # This file
```

### Core Components

- **transcriber.py**: Handles audio extraction, compression, and Gemini API communication
- **app.py**: Flask web server with REST API endpoints
- **transcribe.py**: Command-line interface wrapper
- **config.py**: Centralized configuration management
- **logger.py**: Structured logging setup

## 🔒 Security Features

- ✅ Secure temporary file handling with `NamedTemporaryFile`
- ✅ API keys passed in headers (not URL parameters)
- ✅ Input validation and sanitization
- ✅ File extension whitelisting
- ✅ Subprocess timeout protection
- ✅ Proper error handling and logging
- ✅ Race condition prevention in file cleanup

## 🛠️ Technical Details

### Audio Processing

The application automatically:
1. Detects file type (audio vs. video)
2. Extracts audio from video files using FFmpeg
3. Compresses to 16kHz mono MP3 at 32kbps
4. Base64-encodes for API transmission
5. Cleans up temporary files securely

### API Integration

- Uses Gemini 2.5 Flash for fast, accurate transcription
- Temperature set to 0.1 for deterministic output
- Custom system instructions for each output format
- Comprehensive error handling and validation

### Supported Formats

**Input (Video)**:
- MP4, AVI, MKV, MOV, WebM, FLV, WMV, 3GP

**Input (Audio)**:
- MP3, WAV, M4A, AAC, FLAC, OGG, WMA, Opus

**Output**:
- TXT: Plain text transcription
- SRT: SubRip subtitle format
- VTT: WebVTT subtitle format
- JSON: Structured segments with timestamps

## 📝 Logging

All operations are logged with appropriate levels:
- **INFO**: Normal operations (file uploads, transcription start/complete)
- **WARNING**: Invalid inputs or unusual conditions
- **ERROR**: Processing failures, API errors
- **DEBUG**: Detailed diagnostic information

Logs include timestamps, module names, and full context for troubleshooting.

## 🐛 Troubleshooting

### "FFmpeg not found"
- Ensure FFmpeg is installed and in your system PATH
- Test with: `ffmpeg -version`

### "API request failed"
- Verify your `GEMINI_API_KEY` is set correctly
- Check your API quota at [Google AI Studio](https://makersuite.google.com/)

### "Timeout during processing"
- For very long files, increase timeout values in `config.py`
- Consider splitting large files into smaller segments

### "Unsupported file type"
- Check that your file extension is in `ALLOWED_EXTENSIONS`
- Verify the file isn't corrupted: `ffprobe your_file.mp4`

## 📄 License

This project is open source and available under the MIT License.

## 🙏 Acknowledgments

- **Google Gemini**: For the powerful multimodal AI API
- **FFmpeg**: For exceptional multimedia processing capabilities
- **Flask**: For the lightweight web framework

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

---

Built with ❤️ using Python, Flask, FFmpeg, and Gemini API
