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
- **Comprehensive Summaries**: Detailed end-of-process reports with file info, processing stats, errors, and timing
- **Enhanced Error Detection**: Specific detection and helpful guidance for API errors (content blocking, quota exceeded, etc.)
- **Chunk-Level Error Tracking**: See which chunks succeeded/failed in large file processing with detailed error messages
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

## 📊 Summary & Error Reporting

Every transcription generates a comprehensive summary showing exactly what happened during processing.

### Summary Information Tracked

- **Input Details**: Filename, file size, duration
- **Processing Mode**: Single-file or chunked processing
- **Results**: Output format, character count, success/failure status
- **Timing**: Total processing time
- **Errors & Warnings**: Detailed error messages with helpful guidance
- **Chunk Statistics**: For large files, see which chunks succeeded/failed

### Example Summary Output

```
TRANSCRIPTION SUMMARY
Status: ✓ SUCCESS

Input File:
  Name: lecture.mp4
  Size: 125.50 MB
  Duration: 45:30

Processing:
  Mode: Chunked (15-minute chunks)
  Total Chunks: 3
  Successful: 3/3
  Format: SRT

Output:
  Length: 24,567 characters

✓ No errors or warnings

Processing Time: 3m 45s
```

### API Error Detection

The system specifically detects and provides helpful guidance for:

#### Content Blocked (CONTENT_BLOCKED)
```
🚫 API ERROR DETAILS:
  Type: CONTENT_BLOCKED
  Message: Content was blocked by Gemini's safety filters...

  💡 This content was blocked by Gemini's safety filters.
     The audio may contain prohibited content such as:
     - Harmful or dangerous content
     - Hateful or abusive language
     - Sexually explicit material
     - Content that violates content policies
```

#### Quota Exceeded (QUOTA_EXCEEDED)
```
🚫 API ERROR DETAILS:
  Type: QUOTA_EXCEEDED
  Message: API quota exceeded...

  💡 Your API quota has been exceeded.
     Please wait and try again later, or check your quota at:
     https://makersuite.google.com/
```

#### Recitation Detected (RECITATION)
```
🚫 API ERROR DETAILS:
  Type: RECITATION
  Message: Content was flagged as potential recitation...

  💡 The content was flagged as potential recitation.
     This may indicate copyrighted content in the audio.
```

### Web API Response

When using the web interface, the API returns detailed summary information in JSON format:

```json
{
  "success": true,
  "transcript": "...",
  "summary": {
    "filename": "lecture.mp4",
    "file_size_mb": 125.5,
    "duration": "45:30",
    "output_format": "srt",
    "processing_time": "3m 45s",
    "errors": [],
    "warnings": []
  }
}
```

For errors:

```json
{
  "error": "Content was blocked by safety filters",
  "error_type": "CONTENT_BLOCKED",
  "summary": {
    "filename": "video.mp4",
    "errors": ["API Error (CONTENT_BLOCKED): Content was blocked..."],
    "success": false
  }
}
```

## 🏗️ Architecture

```
my-transcriber/
├── app.py              # Flask web application
├── transcribe.py       # CLI tool
├── transcriber.py      # Core transcription logic
├── chunk_processor.py  # Large file chunking handler
├── summary.py          # Transcription summary tracking
├── config.py           # Centralized configuration
├── logger.py           # Logging setup
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Web UI
└── README.md           # This file
```

### Core Components

- **transcriber.py**: Handles audio extraction, compression, and Gemini API communication with enhanced error detection
- **chunk_processor.py**: Splits large files into chunks, transcribes each, and merges results with error tracking
- **summary.py**: Tracks transcription process details, errors, warnings, and generates comprehensive reports
- **app.py**: Flask web server with REST API endpoints and summary support
- **transcribe.py**: Command-line interface wrapper with formatted summary output
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

### "Content blocked by safety filters" (CONTENT_BLOCKED)
**Cause**: The Gemini API detected content that violates its safety policies.

**Common triggers**:
- Harmful, dangerous, or violent content
- Hateful or abusive language
- Sexually explicit material
- Content promoting illegal activities

**Solutions**:
- Review the audio content to ensure it complies with [Google's AI Principles](https://ai.google/responsibility/principles/)
- If the content is legitimate (e.g., educational, documentary), consider editing or providing additional context via the `--prompt` parameter
- For false positives, you can report the issue to Google AI support

### "API quota exceeded" (QUOTA_EXCEEDED)
**Cause**: You've reached your API rate limit or quota.

**Solutions**:
- Wait for your quota to reset (usually daily or monthly)
- Check your current usage at [Google AI Studio](https://makersuite.google.com/)
- Consider upgrading your API plan if you need higher limits
- For large files with chunking, some chunks may succeed before hitting the limit

### "Recitation detected" (RECITATION)
**Cause**: The API detected potential copyrighted content in the audio.

**Solutions**:
- Ensure you have rights to transcribe the content
- This commonly occurs with music, movie dialogues, or published speeches
- For legitimate use cases, document your rights to the content

### "Chunk failures in large files"
**Cause**: One or more chunks failed during chunked processing.

**What happens**:
- The system continues processing remaining chunks
- Failed chunks are marked in the summary with specific error messages
- You get a partial transcription with error markers

**Solutions**:
- Check the summary to see which chunks failed and why
- Re-process specific failed chunks by adjusting `--chunk-duration` to split differently
- If API errors, check quota and content policies
- For timeout errors, increase timeout values in `config.py`

### "Timeout during processing"
- For very long files, increase timeout values in `config.py`
- Consider using chunking mode with `--enable-chunking`
- Reduce chunk duration with `--chunk-duration` for faster individual processing

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
