import os
import tempfile
import shutil
from flask import Flask, render_template, request, jsonify, send_file, make_response
from transcriber import transcribe_file, get_media_duration, GeminiAPIError
from summary import TranscriptionSummary
from config import (
    MAX_CONTENT_LENGTH, ALLOWED_EXTENSIONS, SUPPORTED_OUTPUT_FORMATS,
    FLASK_HOST, FLASK_PORT, FLASK_DEBUG
)
from logger import setup_logger

logger = setup_logger(__name__)

app = Flask(__name__)

# Configure maximum file size from config
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), 'transcriber_uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename: str) -> bool:
    """
    Check if a filename has an allowed extension.
    
    Args:
        filename: The filename to check
        
    Returns:
        True if the file extension is allowed, False otherwise
    """
    if '.' not in filename:
        return False
    
    ext = filename.rsplit('.', 1)[1].lower()
    
    # SECURITY: Validate extension is in whitelist and doesn't contain path separators
    if ext in ALLOWED_EXTENSIONS and '/' not in ext and '\\' not in ext:
        return True
    
    return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/transcribe', methods=['POST'])
def api_transcribe():
    """
    API endpoint to transcribe uploaded audio/video files.
    
    Returns:
        JSON response with transcription or error message
    """
    if 'file' not in request.files:
        logger.warning("No file part in request")
        return jsonify({'error': 'No file part in the request'}), 400
        
    file = request.files['file']
    if file.filename == '':
        logger.warning("Empty filename in request")
        return jsonify({'error': 'No selected file'}), 400
        
    if not allowed_file(file.filename):
        logger.warning(f"Unsupported file type: {file.filename}")
        return jsonify({
            'error': f'Unsupported file type. Allowed formats: {", ".join(sorted(ALLOWED_EXTENSIONS))}'
        }), 400
        
    output_format = request.form.get('format', 'txt').lower()
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        logger.warning(f"Invalid output format: {output_format}")
        return jsonify({'error': 'Invalid output format requested.'}), 400
        
    prompt_enhancement = request.form.get('prompt', '').strip()
    
    # SECURITY: Sanitize file extension
    filename = file.filename
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    
    # Validate extension again (defense in depth)
    if ext.lstrip('.') not in ALLOWED_EXTENSIONS:
        logger.error(f"Extension validation failed for: {ext}")
        return jsonify({'error': 'Invalid file extension'}), 400
    
    temp_file_path = os.path.join(UPLOAD_FOLDER, f"upload_{os.urandom(8).hex()}{ext}")
    
    # Initialize summary (will be populated even if transcription fails)
    summary = None
    
    try:
        logger.info(f"Saving uploaded file '{filename}' to {temp_file_path}...")
        file.save(temp_file_path)
        
        # Get file size and duration
        file_size_mb = os.path.getsize(temp_file_path) / (1024 * 1024)
        duration = get_media_duration(temp_file_path)
        duration_str = "Unknown"
        if duration is not None:
            mins = int(duration // 60)
            secs = int(duration % 60)
            duration_str = f"{mins:02d}:{secs:02d}"
            
        logger.info(f"Uploaded file saved successfully. Duration: {duration_str}")
        
        # Create summary tracker
        summary = TranscriptionSummary(
            filename=filename,
            file_size_mb=file_size_mb,
            duration_seconds=duration,
            output_format=output_format
        )
        
        # Perform transcription
        logger.info(f"Starting transcription for '{filename}' (format: {output_format})...")
        transcript = transcribe_file(
            file_path=temp_file_path,
            output_format=output_format,
            prompt_enhancement=prompt_enhancement
        )
        
        # Mark success and record output length
        summary.output_length = len(transcript)
        summary.mark_complete(success=True)
        
        logger.info(f"Transcription completed for '{filename}'")
        return jsonify({
            'success': True,
            'filename': filename,
            'duration_seconds': duration,
            'duration_str': duration_str,
            'transcript': transcript,
            'format': output_format,
            'summary': summary.to_dict()
        })
        
    except GeminiAPIError as e:
        # Specific handling for Gemini API errors
        logger.error(f"Gemini API error ({e.error_type}): {e}")
        
        if summary:
            summary.set_api_error(e.error_type, str(e))
            summary.mark_complete(success=False)
        
        # Return detailed error information
        error_response = {
            'error': str(e),
            'error_type': e.error_type
        }
        
        if summary:
            error_response['summary'] = summary.to_dict()
        
        return jsonify(error_response), 500
        
    except FileNotFoundError as e:
        logger.error(f"File not found error: {e}")
        
        if summary:
            summary.add_error(f"File not found: {e}")
            summary.mark_complete(success=False)
        
        error_response = {'error': 'File not found during processing'}
        if summary:
            error_response['summary'] = summary.to_dict()
        
        return jsonify(error_response), 500
        
    except ValueError as e:
        logger.error(f"Value error during transcription: {e}")
        
        if summary:
            summary.add_error(f"Value error: {e}")
            summary.mark_complete(success=False)
        
        error_response = {'error': f'Transcription failed: {str(e)}'}
        if summary:
            error_response['summary'] = summary.to_dict()
        
        return jsonify(error_response), 500
        
    except Exception as e:
        logger.error(f"Unexpected error in /api/transcribe: {e}", exc_info=True)
        
        if summary:
            summary.add_error(f"Unexpected error: {e}")
            summary.mark_complete(success=False)
        
        error_response = {'error': f'An unexpected error occurred: {str(e)}'}
        if summary:
            error_response['summary'] = summary.to_dict()
        
        return jsonify(error_response), 500
        
    finally:
        # IMPROVED CLEANUP: Remove race condition
        if temp_file_path:
            try:
                os.remove(temp_file_path)
                logger.debug(f"Cleaned up temporary uploaded file: {temp_file_path}")
            except FileNotFoundError:
                # File already deleted, that's fine
                pass
            except Exception as e:
                logger.warning(f"Failed to delete uploaded temp file {temp_file_path}: {e}")

@app.route('/api/download', methods=['POST'])
def api_download():
    """
    Downloads the transcript text as a file.
    Expects JSON payload with 'transcript', 'filename', and 'format'.
    
    Returns:
        File download response or error JSON
    """
    data = request.json or {}
    transcript = data.get('transcript', '')
    original_filename = data.get('filename', 'transcript')
    output_format = data.get('format', 'txt').lower()
    
    if not transcript:
        logger.warning("Download requested with no transcript content")
        return jsonify({'error': 'No transcription content provided.'}), 400
    
    # Validate output format
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        logger.warning(f"Invalid download format requested: {output_format}")
        return jsonify({'error': 'Invalid output format'}), 400
        
    base, _ = os.path.splitext(original_filename)
    download_filename = f"{base}.{output_format}"
    
    # Set matching MIME types
    mime_types = {
        'txt': 'text/plain',
        'srt': 'text/plain',
        'vtt': 'text/vtt',
        'json': 'application/json'
    }
    
    mime_type = mime_types.get(output_format, 'text/plain')
    
    logger.info(f"Serving download for '{download_filename}'")
    response = make_response(transcript)
    response.headers['Content-Type'] = f"{mime_type}; charset=utf-8"
    response.headers['Content-Disposition'] = f"attachment; filename=\"{download_filename}\""
    return response

if __name__ == '__main__':
    # Run Flask server with configuration from config.py
    logger.info(f"Starting Flask server on {FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
