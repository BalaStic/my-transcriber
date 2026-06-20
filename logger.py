"""
Centralized logging configuration for the Transcriber application.
Provides structured logging with proper levels and formatting.
"""
import logging
import sys
from config import LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT

def setup_logger(name: str) -> logging.Logger:
    """
    Set up and configure a logger with consistent formatting.
    
    Args:
        name: The name of the logger (typically __name__ from the calling module)
    
    Returns:
        A configured Logger instance
    """
    logger = logging.getLogger(name)
    
    # Only configure if no handlers exist (avoid duplicate handlers)
    if not logger.handlers:
        logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        
        # Formatter
        formatter = logging.Formatter(
            fmt=LOG_FORMAT,
            datefmt=LOG_DATE_FORMAT
        )
        console_handler.setFormatter(formatter)
        
        logger.addHandler(console_handler)
        
        # Prevent propagation to root logger
        logger.propagate = False
    
    return logger
