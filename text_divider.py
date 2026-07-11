#!/usr/bin/env python3
"""Divide a text file into parts of ~30 KB each, splitting at sentence boundaries."""

import argparse
import os
import re
import sys

CHUNK_SIZE_BYTES = 30 * 1024  # ~30 KB


def find_sentence_boundaries(text: str) -> list[int]:
    """
    Find all sentence boundary positions in the text.
    A sentence boundary is defined as the position right after a dot ('.')
    that is followed by whitespace or end of string.
    """
    boundaries = []
    for match in re.finditer(r"\.(?=\s|$)", text):
        boundaries.append(match.end())
    return boundaries


def divide_text(text: str, chunk_size: int = CHUNK_SIZE_BYTES) -> list[str]:
    """
    Divide text into chunks of approximately chunk_size bytes,
    splitting at sentence boundaries.
    """
    boundaries = find_sentence_boundaries(text)

    if not boundaries:
        # No sentence boundaries found — return whole text as one chunk
        return [text]

    chunks = []
    start = 0

    for boundary in boundaries:
        candidate = text[start:boundary]
        if len(candidate.encode("utf-8")) >= chunk_size:
            if start == 0 and not chunks:
                # First chunk already exceeds limit
                pass
            chunks.append(candidate)
            start = boundary

    # Append any remaining text as the last chunk
    remainder = text[start:]
    if remainder.strip():
        chunks.append(remainder)

    # Edge case: a single sentence exceeds chunk_size (still becomes its own chunk)
    if not chunks and text.strip():
        chunks.append(text)

    return chunks


def write_chunks(chunks: list[str], input_path: str) -> list[str]:
    """Write chunks to disk, returning the list of output file paths."""
    base, ext = os.path.splitext(input_path)
    num_digits = max(3, len(str(len(chunks))))

    output_paths = []
    for i, chunk in enumerate(chunks, start=1):
        out_name = f"{base}_part_{i:0{num_digits}d}{ext}"
        with open(out_name, "w", encoding="utf-8") as f:
            f.write(chunk)
        output_paths.append(out_name)

    return output_paths


def main():
    parser = argparse.ArgumentParser(
        description="Divide a text file into ~30 KB chunks, splitting at sentence boundaries."
    )
    parser.add_argument(
        "-i", "--iinput",
        required=True,
        metavar="FILE",
        help="Path to the input text file",
    )
    args = parser.parse_args()

    input_path = args.iinput

    if not os.path.isfile(input_path):
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read()

    if not text.strip():
        print("Warning: input file is empty, no chunks written.", file=sys.stderr)
        sys.exit(0)

    chunks = divide_text(text)

    # Check for oversized single-sentence chunks and warn
    for i, chunk in enumerate(chunks, start=1):
        size = len(chunk.encode("utf-8"))
        if size > CHUNK_SIZE_BYTES:
            sentences = [s.strip() for s in re.split(r"(?<=\.)\s+", chunk) if s.strip()]
            if len(sentences) <= 1:
                print(
                    f"Warning: chunk {i} contains a single sentence "
                    f"exceeding {CHUNK_SIZE_BYTES} bytes ({size} bytes).",
                    file=sys.stderr,
                )

    output_paths = write_chunks(chunks, input_path)

    for path in output_paths:
        size = os.path.getsize(path)
        print(f"{path}  ({size} bytes)")


if __name__ == "__main__":
    main()