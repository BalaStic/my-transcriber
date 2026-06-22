"""
Transcription summary tracking and reporting.
Tracks all details of the transcription process including errors, warnings, and statistics.
"""
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TranscriptionSummary:
    """
    Comprehensive summary of a transcription operation.
    Tracks input details, processing info, results, errors, and statistics.
    """
    # Input details
    filename: str
    file_size_mb: float
    duration_seconds: Optional[float] = None
    
    # Processing details
    output_format: str = "txt"
    chunked_processing: bool = False
    chunk_count: int = 0
    chunk_duration_minutes: int = 0
    
    # Results
    success: bool = False
    output_length: int = 0  # Character count
    
    # Timing
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    
    # Errors and warnings
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Chunk-specific tracking
    chunks_succeeded: int = 0
    chunks_failed: int = 0
    chunk_errors: Dict[int, str] = field(default_factory=dict)
    
    # API-specific errors
    api_error_type: Optional[str] = None  # e.g., "CONTENT_BLOCKED", "QUOTA_EXCEEDED", "INVALID_RESPONSE"
    api_error_message: Optional[str] = None
    
    def mark_complete(self, success: bool = True):
        """Mark the transcription as complete."""
        self.end_time = time.time()
        self.success = success
    
    def add_error(self, error_message: str):
        """Add an error to the summary."""
        self.errors.append(error_message)
    
    def add_warning(self, warning_message: str):
        """Add a warning to the summary."""
        self.warnings.append(warning_message)
    
    def record_chunk_success(self, chunk_index: int):
        """Record that a chunk was successfully transcribed."""
        self.chunks_succeeded += 1
    
    def record_chunk_failure(self, chunk_index: int, error: str):
        """Record that a chunk failed to transcribe."""
        self.chunks_failed += 1
        self.chunk_errors[chunk_index] = error
    
    def set_api_error(self, error_type: str, error_message: str):
        """Set API-specific error information."""
        self.api_error_type = error_type
        self.api_error_message = error_message
        self.add_error(f"API Error ({error_type}): {error_message}")
    
    def get_processing_time(self) -> float:
        """Get the total processing time in seconds."""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time
    
    def get_duration_str(self) -> str:
        """Get formatted duration string (MM:SS)."""
        if self.duration_seconds is None:
            return "Unknown"
        minutes = int(self.duration_seconds // 60)
        seconds = int(self.duration_seconds % 60)
        return f"{minutes:02d}:{seconds:02d}"
    
    def get_processing_time_str(self) -> str:
        """Get formatted processing time string."""
        total_seconds = self.get_processing_time()
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        if minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert summary to dictionary for JSON serialization."""
        return {
            "filename": self.filename,
            "file_size_mb": round(self.file_size_mb, 2),
            "duration": self.get_duration_str(),
            "duration_seconds": self.duration_seconds,
            "output_format": self.output_format,
            "chunked_processing": self.chunked_processing,
            "chunk_count": self.chunk_count,
            "chunks_succeeded": self.chunks_succeeded,
            "chunks_failed": self.chunks_failed,
            "success": self.success,
            "output_length": self.output_length,
            "processing_time": self.get_processing_time_str(),
            "processing_time_seconds": round(self.get_processing_time(), 2),
            "errors": self.errors,
            "warnings": self.warnings,
            "api_error_type": self.api_error_type,
            "api_error_message": self.api_error_message,
        }
    
    def print_summary(self):
        """Print a formatted summary to console."""
        print("\n" + "=" * 60)
        print("TRANSCRIPTION SUMMARY")
        print("=" * 60)
        
        # Status
        status_symbol = "✓" if self.success else "✗"
        status_text = "SUCCESS" if self.success else "FAILED"
        print(f"Status: {status_symbol} {status_text}")
        
        # Input details
        print(f"\nInput File:")
        print(f"  Name: {self.filename}")
        print(f"  Size: {self.file_size_mb:.2f} MB")
        print(f"  Duration: {self.get_duration_str()}")
        
        # Processing details
        print(f"\nProcessing:")
        if self.chunked_processing:
            print(f"  Mode: Chunked ({self.chunk_duration_minutes}-minute chunks)")
            print(f"  Total Chunks: {self.chunk_count}")
            print(f"  Successful: {self.chunks_succeeded}/{self.chunk_count}")
            if self.chunks_failed > 0:
                print(f"  Failed: {self.chunks_failed}/{self.chunk_count}")
        else:
            print(f"  Mode: Single-file")
        print(f"  Format: {self.output_format.upper()}")
        
        # Results
        if self.success:
            print(f"\nOutput:")
            print(f"  Length: {self.output_length:,} characters")
        
        # Errors
        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"  • {error}")
        
        # Warnings
        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  • {warning}")
        
        # Chunk errors (detailed)
        if self.chunk_errors:
            print(f"\n📋 CHUNK FAILURES:")
            for chunk_idx, error in self.chunk_errors.items():
                print(f"  Chunk {chunk_idx + 1}: {error}")
        
        # API errors (special handling)
        if self.api_error_type:
            print(f"\n🚫 API ERROR DETAILS:")
            print(f"  Type: {self.api_error_type}")
            print(f"  Message: {self.api_error_message}")
            
            # Provide helpful guidance based on error type
            if self.api_error_type == "CONTENT_BLOCKED":
                print(f"\n  💡 This content was blocked by Gemini's safety filters.")
                print(f"     The audio may contain prohibited content such as:")
                print(f"     - Harmful or dangerous content")
                print(f"     - Hateful or abusive language")
                print(f"     - Sexually explicit material")
                print(f"     - Content that violates content policies")
            elif self.api_error_type == "QUOTA_EXCEEDED":
                print(f"\n  💡 Your API quota has been exceeded.")
                print(f"     Please wait and try again later, or check your quota at:")
                print(f"     https://makersuite.google.com/")
            elif self.api_error_type == "RECITATION":
                print(f"\n  💡 The content was flagged as potential recitation.")
                print(f"     This may indicate copyrighted content in the audio.")
        
        # No errors message
        if not self.errors and not self.warnings:
            print(f"\n✓ No errors or warnings")
        
        # Timing
        print(f"\nProcessing Time: {self.get_processing_time_str()}")
        print("=" * 60)
