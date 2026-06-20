import os
import sys
import json
import base64
import tempfile
import subprocess
import requests
from typing import Optional

from config import (
    GEMINI_API_BASE_URL, GEMINI_API_KEY, GEMINI_TEMPERATURE,
    AUDIO_EXTENSIONS, FFMPEG_SAMPLE_RATE, FFMPEG_CHANNELS, 
    FFMPEG_BITRATE, FFMPEG_FORMAT, FFMPEG_TIMEOUT, FFPROBE_TIMEOUT
)
from logger import setup_logger

logger = setup_logger(__name__)

def get_media_duration(file_path: str) -> Optional[float]:
    """
    Get the duration of a media file (video or audio) in seconds using ffprobe.
    
    Args:
        file_path: Path to the media file
        
    Returns:
        Duration in seconds, or None if unable to determine
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    try:
        result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True, 
            check=True,
            timeout=FFPROBE_TIMEOUT
        )
        return float(result.stdout.strip())
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout while reading duration with ffprobe for {file_path}")
        return None
    except subprocess.CalledProcessError as e:
        logger.error(f"ffprobe failed: {e.stderr}")
        return None
    except (ValueError, AttributeError) as e:
        logger.error(f"Failed to parse duration output: {e}")
        return None

def extract_audio(video_path: str, audio_path: Optional[str] = None) -> str:
    """
    Extracts audio from a video file and compresses it to a lightweight MP3.
    
    Args:
        video_path: Path to the input video file
        audio_path: Optional path for the output audio file. If None, generates a temp path.
        
    Returns:
        Path to the extracted audio file
        
    Raises:
        subprocess.CalledProcessError: If ffmpeg extraction fails
        subprocess.TimeoutExpired: If extraction takes too long
    """
    if not audio_path:
        temp_dir = tempfile.gettempdir()
        audio_path = os.path.join(temp_dir, f"extracted_audio_{os.path.basename(video_path)}.mp3")
    
    # ffmpeg configuration using values from config
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-ar", FFMPEG_SAMPLE_RATE,
        "-ac", FFMPEG_CHANNELS,
        "-ab", FFMPEG_BITRATE,
        "-f", FFMPEG_FORMAT,
        audio_path
    ]
    
    logger.info(f"Extracting and compressing audio from {video_path}...")
    try:
        subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            check=True,
            timeout=FFMPEG_TIMEOUT
        )
        logger.info(f"Audio extracted successfully to {audio_path}")
        return audio_path
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg timeout while extracting audio from {video_path}")
        raise
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else "Unknown error"
        logger.error(f"FFmpeg audio extraction failed: {error_msg}")
        raise

def is_audio_file(file_path: str) -> bool:
    """
    Determines if a file is an audio file based on common extensions.
    
    Args:
        file_path: Path to the file to check
        
    Returns:
        True if the file is an audio file, False otherwise
    """
    _, ext = os.path.splitext(file_path.lower())
    return ext in AUDIO_EXTENSIONS

def query_gemini_transcription(audio_path: str, output_format: str = "txt", 
                               prompt_enhancement: Optional[str] = None) -> str:
    """
    Encodes audio to base64 and calls the Gemini API to transcribe.
    
    Args:
        audio_path: Path to the audio file to transcribe
        output_format: Output format (txt, srt, vtt, json)
        prompt_enhancement: Optional additional instructions for the transcription
        
    Returns:
        The transcribed text in the requested format
        
    Raises:
        FileNotFoundError: If the audio file doesn't exist
        ValueError: If the API request fails or response is invalid
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
    logger.info(f"Reading and base64-encoding {audio_path}...")
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()
    
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
    
    # Tailor prompt based on the requested output format
    if output_format == "txt":
        system_instruction = (
            "You are an expert audio transcriber. Transcribe the following audio accurately. "
            "Preserve specific technical terms, names, and proper punctuation. Do not summarize, "
            "shorten, or translate the dialogue. If there is only silence or no audible speech, "
            "output '[Silence]'. Otherwise, output ONLY the plain transcription text, with absolutely "
            "no preamble, conversational fillers, or commentary."
        )
    elif output_format == "srt":
        system_instruction = (
            "You are an expert subtitle generator. Transcribe the following audio accurately and format "
            "the output directly as a SubRip (SRT) subtitle file. Each subtitle segment should have a unique "
            "sequence number starting at 1, start and end timestamps in the format HH:MM:SS,mmm, and the "
            "transcribed text. Keep the text brief and easy to read (max 2 lines per segment, approx 40 chars "
            "per line). If there is only silence, output a single cue containing '[Silence]'. Timestamps must be precise "
            "and aligned with the actual audio events. Output ONLY valid SRT, with absolutely no other introductory or concluding text."
        )
    elif output_format == "vtt":
        system_instruction = (
            "You are an expert subtitle generator. Transcribe the following audio accurately and format "
            "the output directly as a WebVTT (.vtt) file. Start with 'WEBVTT' on the very first line, followed "
            "by a blank line, and then standard WebVTT cues with timestamps in the format HH:MM:SS.mmm. "
            "If there is only silence, output a single cue containing '[Silence]'. Timestamps must be precise "
            "and aligned with the audio. Output ONLY valid WebVTT format, with absolutely no other introductory or concluding text."
        )
    elif output_format == "json":
        system_instruction = (
            "You are an expert audio transcriber. Transcribe the following audio accurately and return "
            "the results as a raw JSON array of objects. Each object must represent a transcript segment and contain "
            "exactly three fields: 'start' (segment start time in seconds, e.g. 1.25), 'end' (segment end time "
            "in seconds, e.g. 5.10), and 'text' (transcribed text). If there is only silence, return a single segment "
            "with the text '[Silence]'. Output ONLY the raw JSON array, with no markdown code blocks "
            "like ```json or conversational text."
        )
    else:
        system_instruction = "Transcribe this audio file accurately. If it is silent, respond with '[Silence]'."

    if prompt_enhancement:
        system_instruction += f"\nAdditional guidelines: {prompt_enhancement}"

    # SECURITY FIX: Use header for API key instead of query parameter
    headers = {"Content-Type": "application/json"}
    if GEMINI_API_KEY:
        headers["x-goog-api-key"] = GEMINI_API_KEY
    
    payload = {
        "contents": [{
            "parts": [
                {
                    "inline_data": {
                        "mime_type": "audio/mp3",
                        "data": audio_base64
                    }
                },
                {
                    "text": system_instruction
                }
            ]
        }],
        "generationConfig": {
            "temperature": GEMINI_TEMPERATURE,
        }
    }
    
    logger.info("Sending transcription request to Gemini API...")
    response = requests.post(GEMINI_API_BASE_URL, headers=headers, json=payload)
    
    if response.status_code != 200:
        logger.error(f"Gemini API request failed with status {response.status_code}")
        raise ValueError(f"Gemini API request failed with status {response.status_code}: {response.text}")
    
    # IMPROVED ERROR HANDLING: Validate response structure
    try:
        response_json = response.json()
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response: {e}")
        raise ValueError(f"Invalid JSON response from Gemini API: {response.text}")
    
    # Validate response structure with defensive checks
    if not isinstance(response_json, dict):
        raise ValueError("API response is not a JSON object")
    
    if "candidates" not in response_json:
        raise ValueError(f"No 'candidates' in API response: {response_json}")
    
    candidates = response_json["candidates"]
    if not candidates or len(candidates) == 0:
        raise ValueError("No candidates in API response")
    
    candidate = candidates[0]
    if "content" not in candidate:
        raise ValueError(f"No 'content' in candidate: {candidate}")
    
    content = candidate["content"]
    if "parts" not in content:
        raise ValueError(f"No 'parts' in content: {content}")
    
    parts = content["parts"]
    if not parts or len(parts) == 0:
        raise ValueError("No parts in content")
    
    if "text" not in parts[0]:
        raise ValueError(f"No 'text' in first part: {parts[0]}")
    
    transcript = parts[0]["text"].strip()
    
    # Strip markdown code blocks if present (for JSON format)
    if output_format == "json" and transcript.startswith("```"):
        lines = transcript.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        transcript = "\n".join(lines).strip()
    
    logger.info("Transcription completed successfully")
    return transcript

def transcribe_file(file_path: str, output_format: str = "txt", 
                    prompt_enhancement: Optional[str] = None) -> str:
    """
    High-level function to transcribe a video or audio file.
    If the input is a video, extracts the audio first.
    If the input is an audio file, uses it directly.
    
    Args:
        file_path: Path to the input video or audio file
        output_format: Output format (txt, srt, vtt, json)
        prompt_enhancement: Optional additional instructions for transcription
        
    Returns:
        The transcribed text in the requested format
        
    Raises:
        FileNotFoundError: If the input file doesn't exist
        subprocess.CalledProcessError: If ffmpeg processing fails
        ValueError: If the API request fails
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Input file not found: {file_path}")
        
    is_audio = is_audio_file(file_path)
    temp_audio_file = None
    temp_file_obj = None
    
    try:
        # SECURITY FIX: Use NamedTemporaryFile instead of mktemp()
        temp_file_obj = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        temp_audio_file = temp_file_obj.name
        temp_file_obj.close()
        
        if is_audio:
            # For audio files, we compress/re-encode to mp3 32k for efficient payload size
            logger.info(f"Compressing audio file {file_path}...")
            cmd = [
                "ffmpeg", "-y", "-i", file_path,
                "-ar", FFMPEG_SAMPLE_RATE, 
                "-ac", FFMPEG_CHANNELS, 
                "-ab", FFMPEG_BITRATE, 
                "-f", FFMPEG_FORMAT,
                temp_audio_file
            ]
            subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                check=True,
                timeout=FFMPEG_TIMEOUT
            )
            active_audio_path = temp_audio_file
        else:
            # For video files, extract the audio
            active_audio_path = extract_audio(file_path, temp_audio_file)
            
        transcript = query_gemini_transcription(active_audio_path, output_format, prompt_enhancement)
        return transcript
        
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout while processing {file_path}")
        raise
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else "Unknown error"
        logger.error(f"FFmpeg processing failed: {error_msg}")
        raise
    finally:
        # IMPROVED CLEANUP: Remove race condition
        if temp_audio_file:
            try:
                os.remove(temp_audio_file)
                logger.debug(f"Cleaned up temporary file: {temp_audio_file}")
            except FileNotFoundError:
                # File already deleted, that's fine
                pass
            except Exception as e:
                logger.warning(f"Failed to delete temp file {temp_audio_file}: {e}")
