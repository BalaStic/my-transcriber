#!/usr/bin/env python3
import os
import sys
import argparse
from transcriber import transcribe_file, get_media_duration
from chunk_processor import process_large_file_chunked
from config import (
    SUPPORTED_OUTPUT_FORMATS, ENABLE_CHUNKING, 
    CHUNK_DURATION_MINUTES, CHUNK_THRESHOLD_MB
)
from logger import setup_logger

logger = setup_logger(__name__)

def main():
    parser = argparse.ArgumentParser(
        description="Video and Audio Transcriber App using Gemini API & ffmpeg",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Path to the input video or audio file to transcribe."
    )
    
    parser.add_argument(
        "-o", "--output",
        help="Path to save the transcription. If omitted, prints to standard output\n"
             "and saves to a file with the same name and matching extension (e.g., input.srt)."
    )
    
    parser.add_argument(
        "-f", "--format",
        choices=["txt", "srt", "vtt", "json"],
        default="txt",
        help="Output format. Options: txt, srt, vtt, json (default: txt)"
    )
    
    parser.add_argument(
        "--prompt",
        help="Additional instructions or guidelines for transcription\n"
             "(e.g., 'The speaker is speaking French, please translate to English' or\n"
             "'This is a medical lecture, handle medical terms like cardiac arrest carefully')."
    )
    
    parser.add_argument(
        "--enable-chunking",
        action="store_true",
        default=None,
        help="Force enable chunking mode for large files"
    )
    
    parser.add_argument(
        "--disable-chunking",
        action="store_true",
        default=False,
        help="Force disable chunking mode (process file as single unit)"
    )
    
    parser.add_argument(
        "--chunk-duration",
        type=int,
        default=CHUNK_DURATION_MINUTES,
        help=f"Duration of each chunk in minutes (default: {CHUNK_DURATION_MINUTES})"
    )
    
    parser.add_argument(
        "--chunk-threshold",
        type=int,
        default=CHUNK_THRESHOLD_MB,
        help=f"File size threshold in MB for auto-chunking (default: {CHUNK_THRESHOLD_MB})"
    )
    
    args = parser.parse_args()
    
    input_path = args.input
    if not os.path.exists(input_path):
        logger.error(f"Input file does not exist: {input_path}")
        print(f"Error: Input file does not exist: {input_path}", file=sys.stderr)
        sys.exit(1)
    
    # Validate format
    if args.format not in SUPPORTED_OUTPUT_FORMATS:
        logger.error(f"Invalid format: {args.format}")
        print(f"Error: Invalid format. Supported: {', '.join(SUPPORTED_OUTPUT_FORMATS)}", file=sys.stderr)
        sys.exit(1)
        
    print(f"=== Video Transcriber ===")
    print(f"Input file: {input_path}")
    print(f"Target format: {args.format.upper()}")
    logger.info(f"Starting transcription: {input_path} -> {args.format}")
    
    # Check file size to determine if chunking is needed
    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    print(f"File size: {file_size_mb:.2f} MB")
    
    # Get media duration
    duration = get_media_duration(input_path)
    if duration is not None:
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        print(f"File duration: {minutes:02d}:{seconds:02d} ({duration:.2f} seconds)")
        logger.info(f"Media duration: {duration:.2f} seconds")
    
    # Determine whether to use chunking
    use_chunking = False
    
    if args.disable_chunking:
        use_chunking = False
        logger.info("Chunking disabled by user")
    elif args.enable_chunking:
        use_chunking = True
        logger.info("Chunking forced enabled by user")
    elif ENABLE_CHUNKING and file_size_mb > args.chunk_threshold:
        use_chunking = True
        logger.info(f"Auto-enabling chunking (file size {file_size_mb:.2f}MB > threshold {args.chunk_threshold}MB)")
        print(f"\n⚠️  Large file detected ({file_size_mb:.2f}MB)")
        print(f"⚠️  Enabling chunked processing mode")
        print(f"⚠️  Chunk duration: {args.chunk_duration} minutes\n")
    
    try:
        if use_chunking:
            # Process using chunking
            transcript = process_large_file_chunked(
                file_path=input_path,
                output_format=args.format,
                chunk_duration_minutes=args.chunk_duration,
                prompt_enhancement=args.prompt
            )
        else:
            # Process as single file
            transcript = transcribe_file(
                file_path=input_path,
                output_format=args.format,
                prompt_enhancement=args.prompt
            )
        
        # Determine output path
        output_path = args.output
        if not output_path:
            base_name, _ = os.path.splitext(input_path)
            output_path = f"{base_name}.{args.format}"
        
        # Write transcription to output file
        logger.info(f"Writing transcript to: {output_path}")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(transcript)
            
        print("\n=== Transcription Complete! ===")
        print(f"Saved transcript to: {output_path}")
        logger.info(f"Transcription completed successfully")
        
        # Preview output
        print("\n--- Preview ---")
        preview_lines = transcript.splitlines()[:15]
        print("\n".join(preview_lines))
        if len(preview_lines) < len(transcript.splitlines()):
            print("... [remainder of transcription omitted from preview] ...")
    
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        print(f"\nError: File not found - {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Value error during transcription: {e}")
        print(f"\nError: Transcription failed - {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"\nError: An unexpected error occurred - {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()