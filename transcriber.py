import os
import sys
import json
import base64
import tempfile
import subprocess
import requests
from typing import Optional, Tuple

from config import (
    GEMINI_API_BASE_URL, GEMINI_API_KEY, GEMINI_TEMPERATURE,
    AUDIO_EXTENSIONS, GEMINI_AUDIO_MIME_TYPES, AUDIO_CODEC_TO_EXT,
    FFMPEG_SAMPLE_RATE, FFMPEG_CHANNELS, 
    FFMPEG_BITRATE, FFMPEG_FORMAT, FFMPEG_TIMEOUT, FFPROBE_TIMEOUT,
    MAX_FILE_SIZE_MB
)
from logger import setup_logger

logger = setup_logger(__name__)


class GeminiAPIError(Exception):
    """Custom exception for Gemini API errors with detailed information."""
    
    def __init__(self, message: str, error_type: str = "UNKNOWN", response_data: dict = None):
        """
        Initialize Gemini API error.
        
        Args:
            message: Human-readable error message
            error_type: Error type code (CONTENT_BLOCKED, QUOTA_EXCEEDED, etc.)
            response_data: Full API response for debugging
        """
        super().__init__(message)
        self.error_type = error_type
        self.response_data = response_data or {}

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


def probe_audio_codec(file_path: str) -> Optional[str]:
    """
    Probe a media file (video or audio) to determine its first audio codec using ffprobe.
    
    Args:
        file_path: Path to the media file
        
    Returns:
        Audio codec name (e.g. 'aac', 'mp3', 'opus'), or None if not found
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
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
        codec = result.stdout.strip().lower()
        return codec if codec else None
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        logger.warning(f"Failed to probe audio codec for {file_path}: {e}")
        return None


def _get_mime_type_for_file(file_path: str) -> Tuple[str, str]:
    """
    Determine the appropriate MIME type for a media file.
    
    Args:
        file_path: Path to the audio or video file
        
    Returns:
        Tuple of (mime_type, extension_with_dot)
        Falls back to ('audio/mp3', '.mp3') if the extension is not in Gemini's supported list
    """
    _, ext = os.path.splitext(file_path.lower())
    mime_type = GEMINI_AUDIO_MIME_TYPES.get(ext)
    if mime_type:
        return mime_type, ext
    else:
        logger.warning(f"Unsupported extension '{ext}' for Gemini, will re-encode to MP3")
        return "audio/mp3", ".mp3"


def _get_output_ext_for_codec(codec: str) -> str:
    """
    Get the appropriate output file extension for an audio codec when demuxing.
    
    Args:
        codec: Audio codec name from ffprobe (e.g. 'aac', 'mp3')
        
    Returns:
        File extension including dot (e.g. '.m4a', '.mp3')
        Falls back to '.mp3' for unknown codecs
    """
    return AUDIO_CODEC_TO_EXT.get(codec, ".mp3")


def demux_audio(video_path: str, output_path: str, codec: str) -> str:
    """
    Demux (stream copy) the audio track from a video file without re-encoding.
    This is near-instant (IO-bound) compared to full re-encoding (CPU-bound).
    
    Args:
        video_path: Path to the input video file
        output_path: Path for the output audio file
        codec: Audio codec name
        
    Returns:
        Path to the demuxed audio file
        
    Raises:
        subprocess.CalledProcessError: If ffmpeg demuxing fails
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "copy",
        output_path
    ]
    logger.info(f"Demuxing {codec} audio stream from {video_path} (no re-encoding)...")
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=FFMPEG_TIMEOUT
        )
        logger.info(f"Audio demuxed successfully to {output_path}")
        return output_path
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg timeout while demuxing audio from {video_path}")
        raise
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else "Unknown error"
        logger.warning(f"FFmpeg demuxing failed ({error_msg}), falling back to re-encode")
        raise


def _parse_api_error(response) -> Tuple[str, str]:
    """
    Parse API error response to extract error type and message.
    
    Args:
        response: The HTTP response object from the API
        
    Returns:
        Tuple of (error_type, error_message)
    """
    try:
        error_json = response.json()
        
        # Check for standard error format
        if "error" in error_json:
            error_obj = error_json["error"]
            if isinstance(error_obj, dict):
                message = error_obj.get("message", response.text)
                code = error_obj.get("code", response.status_code)
                status = error_obj.get("status", "")
                
                # Determine error type based on status code and message
                if response.status_code == 429 or "quota" in message.lower():
                    return "QUOTA_EXCEEDED", f"API quota exceeded: {message}"
                elif response.status_code == 403:
                    return "FORBIDDEN", f"Access forbidden: {message}"
                elif response.status_code == 400:
                    return "BAD_REQUEST", f"Invalid request: {message}"
                elif "safety" in message.lower() or "prohibited" in message.lower():
                    return "CONTENT_BLOCKED", f"Content blocked by safety filters: {message}"
                else:
                    return "API_ERROR", message
        
    except:
        pass
    
    # Fallback to generic error based on status code
    if response.status_code == 429:
        return "QUOTA_EXCEEDED", "API quota exceeded. Please try again later."
    elif response.status_code == 403:
        return "FORBIDDEN", "Access forbidden. Check your API key."
    elif response.status_code == 400:
        return "BAD_REQUEST", "Invalid request format."
    else:
        return "API_ERROR", f"API request failed with status {response.status_code}: {response.text}"


def _check_response_for_errors(response_json: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Check response JSON for error indicators.
    
    Args:
        response_json: The parsed JSON response
        
    Returns:
        Tuple of (error_type, error_message) or (None, None) if no error
    """
    # Check for top-level error
    if "error" in response_json:
        error_obj = response_json["error"]
        if isinstance(error_obj, dict):
            message = error_obj.get("message", "Unknown API error")
            return "API_ERROR", message
        else:
            return "API_ERROR", str(error_obj)
    
    # Check for promptFeedback (blocked prompts)
    if "promptFeedback" in response_json:
        feedback = response_json["promptFeedback"]
        if "blockReason" in feedback:
            reason = feedback["blockReason"]
            return "CONTENT_BLOCKED", f"Prompt was blocked: {reason}"
    
    return None, None


def _get_silence_response(output_format: str) -> str:
    """
    Return a format-appropriate 'silence' placeholder string.
    Used when the Gemini API returns an empty content object with no parts.

    Args:
        output_format: One of 'txt', 'srt', 'vtt', 'json'

    Returns:
        A valid, format-correct silence string
    """
    if output_format == "srt":
        return "1\n00:00:00,000 --> 00:00:01,000\n[Silence]\n"
    elif output_format == "vtt":
        return "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n[Silence]\n"
    elif output_format == "json":
        return '[{"start": 0, "end": 0, "text": "[Silence]"}]'
    else:  # txt and any unknown formats
        return "[Silence]"


def _get_blocking_reason_message(finish_reason: str, candidate: dict) -> str:
    """
    Get a detailed message explaining why content was blocked.
    
    Args:
        finish_reason: The finish reason from the candidate
        candidate: The full candidate object
        
    Returns:
        Human-readable error message
    """
    messages = {
        "SAFETY": "Content was blocked by Gemini's safety filters. The audio may contain harmful, dangerous, hateful, or inappropriate content.",
        "PROHIBITED_CONTENT": "Content was flagged as prohibited. The audio may violate Google's content policies.",
        "RECITATION": "Content was flagged as potential recitation of copyrighted material."
    }
    
    base_message = messages.get(finish_reason, f"Content was blocked: {finish_reason}")
    
    # Add safety ratings if available
    if "safetyRatings" in candidate:
        ratings = candidate["safetyRatings"]
        blocked_categories = []
        for rating in ratings:
            if isinstance(rating, dict) and rating.get("blocked", False):
                category = rating.get("category", "UNKNOWN")
                blocked_categories.append(category)
        
        if blocked_categories:
            base_message += f"\nBlocked categories: {', '.join(blocked_categories)}"
    
    return base_message

def query_gemini_transcription(audio_path: str, output_format: str = "txt", 
                               prompt_enhancement: Optional[str] = None,
                               mime_type: str = "audio/mp3") -> str:
    """
    Encodes audio to base64 and calls the Gemini API to transcribe.
    
    Args:
        audio_path: Path to the audio file to transcribe
        output_format: Output format (txt, srt, vtt, json)
        prompt_enhancement: Optional additional instructions for the transcription
        mime_type: MIME type for the audio file (default: audio/mp3)
        
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
                        "mime_type": mime_type,
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
        error_type, error_msg = _parse_api_error(response)
        raise GeminiAPIError(error_msg, error_type=error_type, response_data={"status": response.status_code, "text": response.text})
    
    # IMPROVED ERROR HANDLING: Validate response structure
    try:
        response_json = response.json()
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response: {e}")
        raise GeminiAPIError(
            f"Invalid JSON response from Gemini API: {response.text}", 
            error_type="INVALID_RESPONSE"
        )
    
    # Check for API errors in the response
    error_type, error_msg = _check_response_for_errors(response_json)
    if error_type:
        logger.error(f"API returned error: {error_type} - {error_msg}")
        raise GeminiAPIError(error_msg, error_type=error_type, response_data=response_json)
    
    # Validate response structure with defensive checks
    if not isinstance(response_json, dict):
        raise GeminiAPIError("API response is not a JSON object", error_type="INVALID_RESPONSE")
    
    if "candidates" not in response_json:
        raise GeminiAPIError(
            f"No 'candidates' in API response: {response_json}", 
            error_type="INVALID_RESPONSE",
            response_data=response_json
        )
    
    candidates = response_json["candidates"]
    if not candidates or len(candidates) == 0:
        raise GeminiAPIError("No candidates in API response", error_type="INVALID_RESPONSE")
    
    candidate = candidates[0]
    
    # Check for content filtering/blocking
    if "finishReason" in candidate:
        finish_reason = candidate["finishReason"]
        if finish_reason in ["SAFETY", "PROHIBITED_CONTENT", "RECITATION"]:
            error_msg = _get_blocking_reason_message(finish_reason, candidate)
            logger.error(f"Content blocked by API: {finish_reason}")
            raise GeminiAPIError(error_msg, error_type="CONTENT_BLOCKED", response_data=response_json)
        elif finish_reason == "MAX_TOKENS":
            raise GeminiAPIError(
                "Gemini response was cut off because the audio is too long for a single request (MAX_TOKENS). "
                "Try running with --enable-chunking to split the file into smaller segments.",
                error_type="MAX_TOKENS",
                response_data=response_json
            )
    
    if "content" not in candidate:
        # Check if there's a safety rating or other reason for no content
        if "safetyRatings" in candidate:
            error_msg = "Content was blocked by safety filters"
            logger.error(error_msg)
            raise GeminiAPIError(error_msg, error_type="CONTENT_BLOCKED", response_data=response_json)
        raise GeminiAPIError(
            f"No 'content' in candidate: {candidate}", 
            error_type="INVALID_RESPONSE",
            response_data=response_json
        )
    
    content = candidate["content"]
    if "parts" not in content:
        # content is {} — the model returned an empty response body.
        # Inspect finishReason to give a meaningful reaction.
        finish_reason = candidate.get("finishReason", "UNKNOWN")
        if finish_reason == "MAX_TOKENS":
            raise GeminiAPIError(
                "Gemini response was cut off because the audio is too long for a single request (MAX_TOKENS). "
                "Try running with --enable-chunking to split the file into smaller segments.",
                error_type="MAX_TOKENS",
                response_data=response_json
            )
        elif finish_reason in ("STOP", "OTHER", "UNKNOWN", "MALFORMED_RESPONSE"):
            # Model returned empty content — this is a transcription failure, not genuine silence.
            # Raise an error so no output file is written.
            logger.error(
                f"Gemini returned empty content with no text (finishReason: {finish_reason}). "
                "Transcription failed."
            )
            raise GeminiAPIError(
                f"Gemini returned no transcription content (finishReason: {finish_reason}). "
                "The audio may be too long or in an unsupported format. "
                "Try again with --enable-chunking.",
                error_type="EMPTY_RESPONSE",
                response_data=response_json
            )
        else:
            raise GeminiAPIError(
                f"No 'parts' in content (finishReason: {finish_reason}): {content}",
                error_type="INVALID_RESPONSE",
                response_data=response_json
            )
    
    parts = content["parts"]
    if not parts or len(parts) == 0:
        raise GeminiAPIError("No parts in content", error_type="INVALID_RESPONSE")
    
    # Collect text from ALL parts — Gemini can split long responses across multiple parts
    transcript_parts = []
    for i, part in enumerate(parts):
        if "text" not in part:
            logger.warning(f"Part {i} has no 'text' field: {part}")
            continue
        transcript_parts.append(part["text"].strip())
    
    if not transcript_parts:
        raise GeminiAPIError(
            "No text found in any part of the response",
            error_type="INVALID_RESPONSE",
            response_data=response_json
        )
    
    transcript = "".join(transcript_parts)
    
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

def _should_use_direct_send(file_path: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Determine if a file can be sent directly to Gemini without re-encoding.
    
    Decision logic:
    1. Check if the file extension maps to a Gemini-supported MIME type
    2. Check if the file size is within reasonable limits (avoid sending huge lossless files)
    3. For very large lossless files (WAV, FLAC), prefer re-encoding to reduce payload
    
    Args:
        file_path: Path to the audio file
        
    Returns:
        Tuple of (can_send_directly, mime_type, reason_for_rejection)
    """
    mime_type, ext = _get_mime_type_for_file(file_path)
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    
    # High-bitrate lossless formats may produce massive base64 payloads
    # Re-encode them if they're large to avoid API timeouts/memory issues
    LARGE_LOSSLESS_THRESHOLD_MB = 50
    
    lossless_formats = {'.wav', '.flac'}
    if ext in lossless_formats and file_size_mb > LARGE_LOSSLESS_THRESHOLD_MB:
        return False, None, f"Large lossless file ({file_size_mb:.1f}MB), re-encoding to conserve bandwidth"
    
    # If the MIME type is supported, send directly
    if mime_type != "audio/mp3" or ext == ".mp3":
        return True, mime_type, None
    
    # Extension not in Gemini's supported map (e.g. .wma)
    return False, None, f"Unsupported format '{ext}' for Gemini direct send"


def transcribe_file(file_path: str, output_format: str = "txt", 
                    prompt_enhancement: Optional[str] = None) -> str:
    """
    High-level function to transcribe a video or audio file.
    
    Strategy (in order of preference):
    1. Audio files with Gemini-supported format → send directly (no ffmpeg)
    2. Video files with Gemini-supported audio codec → demux with -acodec copy (near-instant)
    3. Anything else → fall back to re-encoding to MP3 16kHz mono 32kbps
    
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
    active_audio_path = file_path  # Default: use original file
    mime_type = "audio/mp3"
    
    try:
        if is_audio:
            # ---- AUDIO FILE PATH ----
            can_direct, detected_mime, reason = _should_use_direct_send(file_path)
            
            if can_direct:
                logger.info(f"Sending audio file directly to Gemini ({detected_mime}) — skipping ffmpeg")
                active_audio_path = file_path
                mime_type = detected_mime
            else:
                # Re-encode to compact MP3
                logger.info(f"Re-encoding audio to MP3 ({reason if reason else 'unsupported format'})...")
                temp_file_obj = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                temp_audio_file = temp_file_obj.name
                temp_file_obj.close()
                
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
                mime_type = "audio/mp3"
        else:
            # ---- VIDEO FILE PATH ----
            # Probe the actual audio codec inside the video
            codec = probe_audio_codec(file_path)
            
            if codec and codec in AUDIO_CODEC_TO_EXT:
                # Try demuxing (stream copy) — near-instant
                output_ext = _get_output_ext_for_codec(codec)
                temp_file_obj = tempfile.NamedTemporaryFile(suffix=output_ext, delete=False)
                temp_audio_file = temp_file_obj.name
                temp_file_obj.close()
                
                try:
                    active_audio_path = demux_audio(file_path, temp_audio_file, codec)
                    
                    # Determine MIME type from the output extension
                    mime_type = GEMINI_AUDIO_MIME_TYPES.get(output_ext, "audio/mp3")
                    logger.info(f"Demuxed {codec} audio, using MIME type {mime_type}")
                except subprocess.CalledProcessError:
                    # Demuxing failed (e.g. codec incompatible with container)
                    # Clean up the failed temp file and fall back to re-encoding
                    if temp_audio_file:
                        try:
                            os.remove(temp_audio_file)
                        except OSError:
                            pass
                    temp_audio_file = None
                    logger.info(f"Demuxing failed for {codec}, falling back to MP3 re-encode")
                    
                    # Fallback: re-encode to MP3
                    temp_file_obj = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                    temp_audio_file = temp_file_obj.name
                    temp_file_obj.close()
                    active_audio_path = extract_audio(file_path, temp_audio_file)
                    mime_type = "audio/mp3"
            else:
                # Unknown codec or probing failed — re-encode to MP3
                logger.info(f"No supported audio codec found, re-encoding to MP3")
                temp_file_obj = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                temp_audio_file = temp_file_obj.name
                temp_file_obj.close()
                active_audio_path = extract_audio(file_path, temp_audio_file)
                mime_type = "audio/mp3"
        
        transcript = query_gemini_transcription(
            active_audio_path, output_format, prompt_enhancement, mime_type
        )
        return transcript
        
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout while processing {file_path}")
        raise
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else "Unknown error"
        logger.error(f"FFmpeg processing failed: {error_msg}")
        raise
    finally:
        # Cleanup: only delete temp files (not original input files)
        if temp_audio_file and temp_audio_file != file_path:
            try:
                os.remove(temp_audio_file)
                logger.debug(f"Cleaned up temporary file: {temp_audio_file}")
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning(f"Failed to delete temp file {temp_audio_file}: {e}")
