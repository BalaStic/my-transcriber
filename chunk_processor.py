"""
Chunk processor for handling large video files.
Splits large files into smaller chunks, transcribes each, and merges results.
"""
import os
import re
import json
import tempfile
import subprocess
from typing import List, Tuple, Optional
from pathlib import Path

from config import (
    CHUNK_DURATION_MINUTES, FFMPEG_TIMEOUT, FFMPEG_FORMAT,
    FFMPEG_SAMPLE_RATE, FFMPEG_CHANNELS, FFMPEG_BITRATE
)
from logger import setup_logger
from transcriber import transcribe_file, get_media_duration

logger = setup_logger(__name__)


def split_video_into_chunks(video_path: str, chunk_duration_minutes: int) -> Tuple[List[str], str]:
    """
    Split a video file into smaller time-based chunks using FFmpeg.
    
    Args:
        video_path: Path to the input video file
        chunk_duration_minutes: Duration of each chunk in minutes
        
    Returns:
        Tuple of (list of chunk file paths, temp directory path)
        
    Raises:
        subprocess.CalledProcessError: If FFmpeg splitting fails
    """
    # Create temporary directory for chunks
    temp_dir = tempfile.mkdtemp(prefix="transcriber_chunks_")
    logger.info(f"Created temporary directory for chunks: {temp_dir}")
    
    chunk_duration_seconds = chunk_duration_minutes * 60
    base_name = Path(video_path).stem
    file_ext = Path(video_path).suffix
    
    # Pattern for output chunks
    chunk_pattern = os.path.join(temp_dir, f"{base_name}_chunk_%03d{file_ext}")
    
    # FFmpeg command to split video by time
    # -f segment: enables segmenting
    # -segment_time: duration of each segment in seconds
    # -c copy: copy streams without re-encoding (fast and preserves quality)
    # -reset_timestamps 1: reset timestamps for each segment
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-f", "segment",
        "-segment_time", str(chunk_duration_seconds),
        "-c", "copy",
        "-reset_timestamps", "1",
        chunk_pattern
    ]
    
    logger.info(f"Splitting video into {chunk_duration_minutes}-minute chunks...")
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=FFMPEG_TIMEOUT * 2  # Splitting may take longer
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else "Unknown error"
        logger.error(f"FFmpeg splitting failed: {error_msg}")
        raise
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg splitting timeout after {FFMPEG_TIMEOUT * 2} seconds")
        raise
    
    # Get list of created chunk files
    chunk_files = sorted([
        os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
        if f.startswith(f"{base_name}_chunk_") and f.endswith(file_ext)
    ])
    
    logger.info(f"Successfully split video into {len(chunk_files)} chunks")
    return chunk_files, temp_dir


def transcribe_chunks(chunk_files: List[str], output_format: str, 
                      prompt_enhancement: Optional[str] = None) -> List[Tuple[int, str]]:
    """
    Transcribe each chunk file.
    
    Args:
        chunk_files: List of chunk file paths
        output_format: Output format (txt, srt, vtt, json)
        prompt_enhancement: Optional additional instructions
        
    Returns:
        List of tuples (chunk_index, transcription_text)
    """
    results = []
    total_chunks = len(chunk_files)
    
    for idx, chunk_file in enumerate(chunk_files, 1):
        logger.info(f"Transcribing chunk {idx}/{total_chunks}: {Path(chunk_file).name}")
        print(f"\n[{idx}/{total_chunks}] Processing chunk: {Path(chunk_file).name}")
        
        try:
            # Get chunk duration for progress reporting
            duration = get_media_duration(chunk_file)
            if duration:
                mins = int(duration // 60)
                secs = int(duration % 60)
                print(f"    Duration: {mins:02d}:{secs:02d}")
            
            transcript = transcribe_file(
                file_path=chunk_file,
                output_format=output_format,
                prompt_enhancement=prompt_enhancement
            )
            
            results.append((idx - 1, transcript))  # 0-indexed
            print(f"    ✓ Chunk {idx} transcribed successfully")
            logger.info(f"Chunk {idx}/{total_chunks} completed")
            
        except Exception as e:
            logger.error(f"Failed to transcribe chunk {idx}: {e}")
            print(f"    ✗ Error transcribing chunk {idx}: {e}")
            # Continue with other chunks even if one fails
            results.append((idx - 1, f"[ERROR: Chunk {idx} transcription failed: {e}]"))
    
    return results


def merge_txt_transcriptions(chunks: List[Tuple[int, str]]) -> str:
    """
    Merge plain text transcriptions.
    
    Args:
        chunks: List of (index, transcription) tuples
        
    Returns:
        Merged transcription text
    """
    # Sort by index
    sorted_chunks = sorted(chunks, key=lambda x: x[0])
    
    # Join with double newline for paragraph separation
    merged = "\n\n".join(text for _, text in sorted_chunks)
    
    logger.info("Merged TXT transcriptions")
    return merged


def merge_srt_transcriptions(chunks: List[Tuple[int, str]], 
                             chunk_duration_minutes: int) -> str:
    """
    Merge SRT subtitle transcriptions with timestamp adjustments.
    
    Args:
        chunks: List of (index, transcription) tuples
        chunk_duration_minutes: Duration of each chunk for timestamp offset
        
    Returns:
        Merged SRT transcription
    """
    sorted_chunks = sorted(chunks, key=lambda x: x[0])
    merged_entries = []
    sequence_number = 1
    
    for chunk_idx, srt_content in sorted_chunks:
        # Calculate time offset for this chunk
        offset_seconds = chunk_idx * chunk_duration_minutes * 60
        
        # Parse SRT entries
        entries = parse_srt(srt_content)
        
        for entry in entries:
            # Adjust timestamps
            adjusted_start = add_seconds_to_timestamp(entry['start'], offset_seconds)
            adjusted_end = add_seconds_to_timestamp(entry['end'], offset_seconds)
            
            # Create new entry with updated sequence number and timestamps
            merged_entries.append(
                f"{sequence_number}\n"
                f"{adjusted_start} --> {adjusted_end}\n"
                f"{entry['text']}\n"
            )
            sequence_number += 1
    
    merged = "\n".join(merged_entries)
    logger.info(f"Merged SRT transcriptions ({sequence_number - 1} total subtitles)")
    return merged


def merge_vtt_transcriptions(chunks: List[Tuple[int, str]], 
                             chunk_duration_minutes: int) -> str:
    """
    Merge WebVTT subtitle transcriptions with timestamp adjustments.
    
    Args:
        chunks: List of (index, transcription) tuples
        chunk_duration_minutes: Duration of each chunk for timestamp offset
        
    Returns:
        Merged VTT transcription
    """
    sorted_chunks = sorted(chunks, key=lambda x: x[0])
    merged_cues = []
    
    for chunk_idx, vtt_content in sorted_chunks:
        # Calculate time offset for this chunk
        offset_seconds = chunk_idx * chunk_duration_minutes * 60
        
        # Parse VTT cues (skip WEBVTT header)
        cues = parse_vtt(vtt_content)
        
        for cue in cues:
            # Adjust timestamps
            adjusted_start = add_seconds_to_timestamp(cue['start'], offset_seconds, vtt_format=True)
            adjusted_end = add_seconds_to_timestamp(cue['end'], offset_seconds, vtt_format=True)
            
            # Create new cue with updated timestamps
            merged_cues.append(
                f"{adjusted_start} --> {adjusted_end}\n"
                f"{cue['text']}\n"
            )
    
    # Add WEBVTT header
    merged = "WEBVTT\n\n" + "\n".join(merged_cues)
    logger.info(f"Merged VTT transcriptions ({len(merged_cues)} total cues)")
    return merged


def merge_json_transcriptions(chunks: List[Tuple[int, str]], 
                              chunk_duration_minutes: int) -> str:
    """
    Merge JSON transcriptions with timestamp adjustments.
    
    Args:
        chunks: List of (index, transcription) tuples
        chunk_duration_minutes: Duration of each chunk for timestamp offset
        
    Returns:
        Merged JSON transcription
    """
    sorted_chunks = sorted(chunks, key=lambda x: x[0])
    merged_segments = []
    
    for chunk_idx, json_content in sorted_chunks:
        # Calculate time offset for this chunk
        offset_seconds = chunk_idx * chunk_duration_minutes * 60
        
        try:
            segments = json.loads(json_content)
            
            if not isinstance(segments, list):
                logger.warning(f"Chunk {chunk_idx} JSON is not an array, skipping")
                continue
            
            for segment in segments:
                # Adjust timestamps
                adjusted_segment = segment.copy()
                if 'start' in adjusted_segment:
                    adjusted_segment['start'] = adjusted_segment['start'] + offset_seconds
                if 'end' in adjusted_segment:
                    adjusted_segment['end'] = adjusted_segment['end'] + offset_seconds
                
                merged_segments.append(adjusted_segment)
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON for chunk {chunk_idx}: {e}")
            continue
    
    merged = json.dumps(merged_segments, indent=2, ensure_ascii=False)
    logger.info(f"Merged JSON transcriptions ({len(merged_segments)} total segments)")
    return merged


def parse_srt(srt_content: str) -> List[dict]:
    """Parse SRT content into structured entries."""
    entries = []
    # Split by double newline to get individual entries
    blocks = re.split(r'\n\s*\n', srt_content.strip())
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        
        # lines[0] is sequence number
        # lines[1] is timestamp
        # lines[2:] is text
        timestamp_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', lines[1])
        if timestamp_match:
            entries.append({
                'start': timestamp_match.group(1),
                'end': timestamp_match.group(2),
                'text': '\n'.join(lines[2:])
            })
    
    return entries


def parse_vtt(vtt_content: str) -> List[dict]:
    """Parse WebVTT content into structured cues."""
    cues = []
    # Remove WEBVTT header
    content = re.sub(r'^WEBVTT\s*\n+', '', vtt_content, flags=re.IGNORECASE)
    
    # Split by double newline to get individual cues
    blocks = re.split(r'\n\s*\n', content.strip())
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue
        
        # First line is timestamp, rest is text
        timestamp_match = re.match(r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})', lines[0])
        if timestamp_match:
            cues.append({
                'start': timestamp_match.group(1),
                'end': timestamp_match.group(2),
                'text': '\n'.join(lines[1:])
            })
    
    return cues


def add_seconds_to_timestamp(timestamp: str, seconds: float, vtt_format: bool = False) -> str:
    """
    Add seconds to a timestamp string.
    
    Args:
        timestamp: Timestamp in SRT (HH:MM:SS,mmm) or VTT (HH:MM:SS.mmm) format
        seconds: Seconds to add
        vtt_format: True for VTT format (. separator), False for SRT (, separator)
        
    Returns:
        Adjusted timestamp in the same format
    """
    # Parse timestamp
    if vtt_format:
        # VTT format: HH:MM:SS.mmm
        match = re.match(r'(\d{2}):(\d{2}):(\d{2})\.(\d{3})', timestamp)
        separator = '.'
    else:
        # SRT format: HH:MM:SS,mmm
        match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', timestamp)
        separator = ','
    
    if not match:
        logger.warning(f"Invalid timestamp format: {timestamp}")
        return timestamp
    
    hours, mins, secs, millis = map(int, match.groups())
    
    # Convert to total milliseconds
    total_ms = (hours * 3600 + mins * 60 + secs) * 1000 + millis
    
    # Add offset
    total_ms += int(seconds * 1000)
    
    # Convert back to components
    hours = total_ms // 3600000
    total_ms %= 3600000
    mins = total_ms // 60000
    total_ms %= 60000
    secs = total_ms // 1000
    millis = total_ms % 1000
    
    return f"{hours:02d}:{mins:02d}:{secs:02d}{separator}{millis:03d}"


def cleanup_chunks(temp_dir: str) -> None:
    """
    Remove all chunk files and temporary directory.
    
    Args:
        temp_dir: Path to temporary directory containing chunks
    """
    try:
        import shutil
        shutil.rmtree(temp_dir)
        logger.info(f"Cleaned up temporary chunk directory: {temp_dir}")
    except Exception as e:
        logger.warning(f"Failed to clean up chunk directory {temp_dir}: {e}")


def process_large_file_chunked(file_path: str, output_format: str = "txt",
                               chunk_duration_minutes: int = CHUNK_DURATION_MINUTES,
                               prompt_enhancement: Optional[str] = None) -> str:
    """
    Process a large file by splitting into chunks, transcribing, and merging.
    
    Args:
        file_path: Path to the input video/audio file
        output_format: Output format (txt, srt, vtt, json)
        chunk_duration_minutes: Duration of each chunk in minutes
        prompt_enhancement: Optional additional instructions
        
    Returns:
        Complete merged transcription
    """
    chunk_files = []
    temp_dir = None
    
    try:
        # Step 1: Split into chunks
        print(f"\n{'='*60}")
        print(f"CHUNKED PROCESSING MODE")
        print(f"{'='*60}")
        print(f"Chunk duration: {chunk_duration_minutes} minutes")
        
        chunk_files, temp_dir = split_video_into_chunks(file_path, chunk_duration_minutes)
        print(f"✓ Video split into {len(chunk_files)} chunks\n")
        
        # Step 2: Transcribe each chunk
        print(f"{'='*60}")
        print(f"TRANSCRIBING CHUNKS")
        print(f"{'='*60}")
        
        chunk_transcriptions = transcribe_chunks(chunk_files, output_format, prompt_enhancement)
        
        # Step 3: Merge results
        print(f"\n{'='*60}")
        print(f"MERGING RESULTS")
        print(f"{'='*60}")
        
        if output_format == "txt":
            merged = merge_txt_transcriptions(chunk_transcriptions)
        elif output_format == "srt":
            merged = merge_srt_transcriptions(chunk_transcriptions, chunk_duration_minutes)
        elif output_format == "vtt":
            merged = merge_vtt_transcriptions(chunk_transcriptions, chunk_duration_minutes)
        elif output_format == "json":
            merged = merge_json_transcriptions(chunk_transcriptions, chunk_duration_minutes)
        else:
            merged = merge_txt_transcriptions(chunk_transcriptions)
        
        print(f"✓ Results merged successfully\n")
        
        return merged
        
    finally:
        # Step 4: Cleanup
        if temp_dir:
            print(f"{'='*60}")
            print(f"CLEANUP")
            print(f"{'='*60}")
            cleanup_chunks(temp_dir)
            print(f"✓ Temporary chunks removed\n")
