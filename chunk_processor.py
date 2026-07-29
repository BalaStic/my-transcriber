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
    FFMPEG_SAMPLE_RATE, FFMPEG_CHANNELS, FFMPEG_BITRATE,
    SILENCE_MIN_DURATION, SILENCE_NOISE_THRESHOLD, SILENCE_SEARCH_WINDOW
)
from logger import setup_logger
from transcriber import transcribe_file, get_media_duration, GeminiAPIError

logger = setup_logger(__name__)


def find_silence_cut_points(
    video_path: str,
    chunk_duration_seconds: float,
    total_duration: float,
    min_silence_duration: float = SILENCE_MIN_DURATION,
    noise_threshold_db: int = SILENCE_NOISE_THRESHOLD,
    search_window: float = SILENCE_SEARCH_WINDOW,
) -> List[float]:
    """
    Detect silence periods in a media file and return silence-snapped cut points.

    For each ideal cut point (chunk_duration_seconds, 2*chunk_duration_seconds, …),
    this function searches ONLY in the window [ideal_cut - search_window, ideal_cut]
    for a silence of at least min_silence_duration seconds.  The midpoint of the
    latest qualifying silence found in that window is used as the actual cut point.
    If no qualifying silence is found, the ideal cut point is used unchanged.

    Args:
        video_path: Path to the media file.
        chunk_duration_seconds: Ideal duration of each chunk in seconds.
        total_duration: Total duration of the file in seconds.
        min_silence_duration: Minimum silence length (seconds) to qualify.
        noise_threshold_db: dB threshold for silence detection (negative number).
        search_window: Seconds to look BEFORE each ideal cut point.

    Returns:
        List of actual cut points in seconds (excludes 0 and total_duration).
    """
    # Build ideal cut points
    ideal_cuts = []
    t = chunk_duration_seconds
    while t < total_duration - 1.0:  # leave at least 1 s for the last chunk
        ideal_cuts.append(t)
        t += chunk_duration_seconds

    if not ideal_cuts:
        return []

    # Run FFmpeg silencedetect on the full file
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-af", f"silencedetect=noise={noise_threshold_db}dB:d={min_silence_duration}",
        "-f", "null",
        "-"
    ]
    logger.info("Running silence detection…")
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=FFMPEG_TIMEOUT * 2
        )
        output = result.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        logger.warning("Silence detection timed out; falling back to time-based cuts")
        return ideal_cuts

    # Parse silence_start / silence_end pairs
    silence_starts = [float(m) for m in re.findall(r"silence_start:\s*([\d.]+)", output)]
    silence_ends   = [float(m) for m in re.findall(r"silence_end:\s*([\d.]+)", output)]

    # Build list of (silence_start, silence_end) pairs
    silences: List[Tuple[float, float]] = []
    for i, s_start in enumerate(silence_starts):
        if i < len(silence_ends):
            silences.append((s_start, silence_ends[i]))
        # If no matching end, the silence runs to EOF — we skip it for safety

    logger.info(f"Detected {len(silences)} silence period(s) in the file")

    # Snap each ideal cut to the nearest qualifying silence before it
    actual_cuts: List[float] = []
    for ideal in ideal_cuts:
        window_start = ideal - search_window
        best: Optional[float] = None  # midpoint of best candidate

        for s_start, s_end in silences:
            # Silence must end at or before the ideal cut point
            # and its start must be within the search window
            if s_start >= window_start and s_end <= ideal:
                mid = (s_start + s_end) / 2.0
                # Among all candidates, prefer the latest one (closest to ideal)
                if best is None or mid > best:
                    best = mid

        if best is not None:
            logger.info(
                f"Ideal cut {ideal:.1f}s → silence-snapped to {best:.1f}s "
                f"(saved {ideal - best:.1f}s)"
            )
            actual_cuts.append(best)
        else:
            logger.info(
                f"Ideal cut {ideal:.1f}s → no silence found in window "
                f"[{max(0, ideal - search_window):.1f}s, {ideal:.1f}s]; "
                f"using original time"
            )
            actual_cuts.append(ideal)

    return actual_cuts


def split_video_into_chunks(
    video_path: str,
    chunk_duration_minutes: int,
) -> Tuple[List[str], str, List[float]]:
    """
    Split a video file into silence-aware chunks using FFmpeg.

    For each ideal chunk boundary, the function searches ONLY before that point
    (within SILENCE_SEARCH_WINDOW seconds) for a silence of at least
    SILENCE_MIN_DURATION seconds and cuts there.  If no silence is found the
    original time boundary is used.

    Args:
        video_path: Path to the input video file
        chunk_duration_minutes: Target duration of each chunk in minutes

    Returns:
        Tuple of:
          - list of chunk file paths (sorted)
          - temp directory path
          - list of actual start times (seconds) for each chunk

    Raises:
        subprocess.CalledProcessError: If an FFmpeg splitting command fails
    """
    # Create temporary directory for chunks
    temp_dir = tempfile.mkdtemp(prefix="transcriber_chunks_")
    logger.info(f"Created temporary directory for chunks: {temp_dir}")

    chunk_duration_seconds = chunk_duration_minutes * 60
    base_name = Path(video_path).stem
    file_ext = Path(video_path).suffix

    # Get total duration
    total_duration = get_media_duration(video_path)
    if not total_duration:
        raise RuntimeError(f"Could not determine duration of {video_path}")

    # Find silence-snapped cut points
    cut_points = find_silence_cut_points(
        video_path, chunk_duration_seconds, total_duration
    )

    # Build segment ranges: [(start, end), …]
    boundaries = [0.0] + cut_points + [total_duration]
    segments = [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]

    logger.info(
        f"Splitting '{Path(video_path).name}' into {len(segments)} chunk(s) "
        f"at silence-aware boundaries…"
    )

    chunk_files: List[str] = []
    for idx, (seg_start, seg_end) in enumerate(segments):
        out_path = os.path.join(temp_dir, f"{base_name}_chunk_{idx:03d}{file_ext}")

        cmd = [
            "ffmpeg",
            "-ss", str(seg_start),
            "-to", str(seg_end),
            "-i", video_path,
            "-c", "copy",
            out_path,
        ]

        try:
            subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=FFMPEG_TIMEOUT * 2,
            )
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode("utf-8", errors="replace") if e.stderr else "Unknown error"
            logger.error(f"FFmpeg failed for chunk {idx}: {error_msg}")
            raise
        except subprocess.TimeoutExpired:
            logger.error(f"FFmpeg timeout for chunk {idx} after {FFMPEG_TIMEOUT * 2}s")
            raise

        chunk_files.append(out_path)

    chunk_start_times = [seg[0] for seg in segments]
    logger.info(f"Successfully split video into {len(chunk_files)} chunk(s)")
    return chunk_files, temp_dir, chunk_start_times


def transcribe_chunks(chunk_files: List[str], output_format: str, 
                      prompt_enhancement: Optional[str] = None,
                      summary=None,
                      debug_audio_paths: Optional[List[str]] = None,
                      temp_dir: Optional[str] = None) -> List[Tuple[int, str]]:
    """
    Transcribe each chunk file.
    
    Args:
        chunk_files: List of chunk file paths
        output_format: Output format (txt, srt, vtt, json)
        prompt_enhancement: Optional additional instructions
        summary: Optional TranscriptionSummary object for tracking
        debug_audio_paths: Optional list to collect temp audio paths on error (for debugging)
        temp_dir: Optional directory for temporary audio files created during transcription.
                  Pass the chunk directory to co-locate temp audio with the video chunks.
        
    Returns:
        List of tuples (chunk_index, transcription_text)
        
    Raises:
        GeminiAPIError: If a chunk fails with an API error (partial results may exist)
        Exception: If a chunk fails with a non-API error (partial results may exist)
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
            
            # Use an error collector so transcribe_file can preserve its temp audio on failure
            error_collector = {}
            transcript = transcribe_file(
                file_path=chunk_file,
                output_format=output_format,
                prompt_enhancement=prompt_enhancement,
                _error_collector=error_collector,
                temp_dir=temp_dir
            )
            
            results.append((idx, transcript))  # 1-indexed
            print(f"    ✓ Chunk {idx} transcribed successfully")
            logger.info(f"Chunk {idx}/{total_chunks} completed")

            # Track success in summary
            if summary:
                summary.record_chunk_success(idx)
            
        except GeminiAPIError as e:
            # Specific API error handling
            error_msg = f"API Error ({e.error_type}): {str(e)}"
            logger.error(f"Failed to transcribe chunk {idx}: {error_msg}")
            print(f"    ✗ {error_msg}")
            
            # Collect preserved temp audio path for debug output
            if debug_audio_paths is not None and 'temp_audio' in error_collector:
                debug_audio_paths.append(error_collector['temp_audio'])
            
            # Track in summary
            if summary:
                summary.record_chunk_failure(idx, error_msg)
                # If this is a content block on first chunk, note it specially
                if e.error_type == "CONTENT_BLOCKED" and idx == 1:
                    summary.set_api_error(e.error_type, str(e))
            
            # Attach partial results to the exception so the caller can save them
            e.partial_results = results
            raise
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to transcribe chunk {idx}: {error_msg}")
            print(f"    ✗ Error transcribing chunk {idx}: {error_msg}")
            
            # Collect preserved temp audio path for debug output
            if debug_audio_paths is not None and 'temp_audio' in error_collector:
                debug_audio_paths.append(error_collector['temp_audio'])
            
            # Track in summary
            if summary:
                summary.record_chunk_failure(idx, error_msg)

            # Attach partial results to the exception so the caller can save them
            e.partial_results = results
            raise
    
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
                             chunk_start_times: List[float]) -> str:
    """
    Merge SRT subtitle transcriptions with timestamp adjustments.

    Args:
        chunks: List of (index, transcription) tuples
        chunk_start_times: Actual start time (seconds) for each chunk index

    Returns:
        Merged SRT transcription
    """
    sorted_chunks = sorted(chunks, key=lambda x: x[0])
    merged_entries = []
    sequence_number = 1

    for chunk_idx, srt_content in sorted_chunks:
        # chunk_idx is 1-based; chunk_start_times is a 0-based list
        offset_seconds = chunk_start_times[chunk_idx - 1] if 0 < chunk_idx <= len(chunk_start_times) else 0.0

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
                             chunk_start_times: List[float]) -> str:
    """
    Merge WebVTT subtitle transcriptions with timestamp adjustments.

    Args:
        chunks: List of (index, transcription) tuples
        chunk_start_times: Actual start time (seconds) for each chunk index

    Returns:
        Merged VTT transcription
    """
    sorted_chunks = sorted(chunks, key=lambda x: x[0])
    merged_cues = []

    for chunk_idx, vtt_content in sorted_chunks:
        # chunk_idx is 1-based; chunk_start_times is a 0-based list
        offset_seconds = chunk_start_times[chunk_idx - 1] if 0 < chunk_idx <= len(chunk_start_times) else 0.0

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
                              chunk_start_times: List[float]) -> str:
    """
    Merge JSON transcriptions with timestamp adjustments.

    Args:
        chunks: List of (index, transcription) tuples
        chunk_start_times: Actual start time (seconds) for each chunk index

    Returns:
        Merged JSON transcription
    """
    sorted_chunks = sorted(chunks, key=lambda x: x[0])
    merged_segments = []

    for chunk_idx, json_content in sorted_chunks:
        # chunk_idx is 1-based; chunk_start_times is a 0-based list
        offset_seconds = chunk_start_times[chunk_idx - 1] if 0 < chunk_idx <= len(chunk_start_times) else 0.0

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
                               prompt_enhancement: Optional[str] = None,
                               summary=None) -> str:
    """
    Process a large file by splitting into chunks, transcribing, and merging.
    
    Args:
        file_path: Path to the input video/audio file
        output_format: Output format (txt, srt, vtt, json)
        chunk_duration_minutes: Duration of each chunk in minutes
        prompt_enhancement: Optional additional instructions
        summary: Optional TranscriptionSummary object for tracking
        
    Returns:
        Complete merged transcription
        
    Raises:
        GeminiAPIError: If a chunk fails with an API error
        Exception: If a chunk fails with a non-API error
    """
    chunk_files = []
    temp_dir = None
    chunk_start_times: List[float] = []
    success = False
    debug_audio_paths: List[str] = []
    chunk_transcriptions: List[Tuple[int, str]] = []

    try:
        # Step 1: Split into chunks
        print(f"\n{'='*60}")
        print(f"CHUNKED PROCESSING MODE")
        print(f"{'='*60}")
        print(f"Chunk duration: {chunk_duration_minutes} minutes")

        chunk_files, temp_dir, chunk_start_times = split_video_into_chunks(file_path, chunk_duration_minutes)
        print(f"✓ Video split into {len(chunk_files)} chunks\n")

        # Update summary with chunk count
        if summary:
            summary.chunk_count = len(chunk_files)

        # Step 2: Transcribe each chunk
        print(f"{'='*60}")
        print(f"TRANSCRIBING CHUNKS")
        print(f"{'='*60}")

        chunk_transcriptions = transcribe_chunks(
            chunk_files, output_format, prompt_enhancement, summary, debug_audio_paths,
            temp_dir=temp_dir
        )

        # Step 3: Merge results
        print(f"\n{'='*60}")
        print(f"MERGING RESULTS")
        print(f"{'='*60}")

        if output_format == "txt":
            merged = merge_txt_transcriptions(chunk_transcriptions)
        elif output_format == "srt":
            merged = merge_srt_transcriptions(chunk_transcriptions, chunk_start_times)
        elif output_format == "vtt":
            merged = merge_vtt_transcriptions(chunk_transcriptions, chunk_start_times)
        elif output_format == "json":
            merged = merge_json_transcriptions(chunk_transcriptions, chunk_start_times)
        else:
            merged = merge_txt_transcriptions(chunk_transcriptions)

        print(f"✓ Results merged successfully\n")
        success = True
        return merged

    except (GeminiAPIError, Exception) as e:
        # Save partial transcription if we have any results
        partial_results = getattr(e, 'partial_results', chunk_transcriptions)
        if temp_dir and partial_results:
            _save_partial_transcription(
                partial_results, file_path, output_format,
                chunk_start_times, temp_dir
            )
        # Re-raise so the caller handles the error
        raise
        
    finally:
        if temp_dir:
            if success:
                # Step 4: Cleanup — only on success
                print(f"{'='*60}")
                print(f"CLEANUP")
                print(f"{'='*60}")
                cleanup_chunks(temp_dir)
                print(f"✓ Temporary chunks removed\n")
            else:
                # On failure: keep chunks so the user can inspect them
                print(f"\n{'='*60}")
                print(f"DEBUG: CHUNK FILES PRESERVED (not deleted due to error)")
                print(f"{'='*60}")
                print(f"Temp directory: {temp_dir}")
                existing = [f for f in chunk_files if os.path.exists(f)]
                if existing:
                    print(f"Chunk files ({len(existing)}):")
                    for chunk_path in existing:
                        print(f"  {chunk_path}")
                else:
                    print(f"  (no chunk files found in {temp_dir})")
                if debug_audio_paths:
                    print(f"\nTemp audio files ({len(debug_audio_paths)}):")
                    for audio_path in debug_audio_paths:
                        print(f"  {audio_path}")
                print(f"{'='*60}\n")
                logger.info(f"Chunk files preserved for debugging in: {temp_dir}")


def _save_partial_transcription(
    partial_results: List[Tuple[int, str]],
    file_path: str,
    output_format: str,
    chunk_start_times: List[float],
    temp_dir: str
) -> None:
    """
    Save a partial transcription to the chunk temp directory on error.

    Args:
        partial_results: List of (chunk_index, transcription_text) tuples
        file_path: Original input file path (used for base name)
        output_format: Output format (txt, srt, vtt, json)
        chunk_start_times: Actual start time (seconds) for each chunk index
        temp_dir: Directory where chunks are stored (partial file saved here too)
    """
    if not partial_results:
        return

    base_name = Path(file_path).stem
    partial_path = os.path.join(temp_dir, f"{base_name}_partial.{output_format}")

    try:
        # Merge partial results using the same merge functions
        if output_format == "txt":
            merged = merge_txt_transcriptions(partial_results)
        elif output_format == "srt":
            merged = merge_srt_transcriptions(partial_results, chunk_start_times)
        elif output_format == "vtt":
            merged = merge_vtt_transcriptions(partial_results, chunk_start_times)
        elif output_format == "json":
            merged = merge_json_transcriptions(partial_results, chunk_start_times)
        else:
            merged = merge_txt_transcriptions(partial_results)
        
        with open(partial_path, "w", encoding="utf-8") as f:
            f.write(merged)
        
        print(f"\n{'='*60}")
        print(f"⚠️  PARTIAL TRANSCRIPTION SAVED")
        print(f"{'='*60}")
        print(f"  {len(partial_results)} of {len(partial_results) + 1}+ chunks completed")
        print(f"  Saved to: {partial_path}")
        print(f"  You can use this file to continue in a next session.")
        print(f"{'='*60}\n")
        logger.info(f"Partial transcription saved to: {partial_path}")
        
    except Exception as e:
        logger.error(f"Failed to save partial transcription: {e}")
        print(f"\n⚠️  Could not save partial transcription: {e}\n")
