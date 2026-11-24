"""
Media Organizer Pro - Professional Automation Tool
Organizes video, image, and audio files intelligently using FFmpeg and ML.
"""

from pathlib import Path
from datetime import datetime
from enum import Enum

try:
    from tools import photo_date
except ImportError:  # imported as a package
    from .tools import photo_date
import logging

class FileType(Enum):
    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    UNKNOWN = "unknown"

class MediaOrganizer:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.logger = logging.getLogger(__name__)

    def classify_file(self, file_path: Path) -> FileType:
        """Classify file type based on extension."""
        extensions = {
            FileType.VIDEO: {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'},
            FileType.IMAGE: {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'},
            FileType.AUDIO: {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma'},
            FileType.DOCUMENT: {'.pdf', '.doc', '.docx', '.txt', '.xls', '.xlsx'},
        }

        suffix = file_path.suffix.lower()
        for ftype, exts in extensions.items():
            if suffix in exts:
                return ftype
        return FileType.UNKNOWN

    def generate_folder_name(self, file_path: Path, ftype: FileType, fmt: str | None = None) -> str:
        """Folder for the file, from folder_format (default {type}/{%Y}/{%B}). Raises ValueError if unsupported."""
        from config import DEFAULT_FOLDER_FORMAT, validate_folder_format
        fmt = validate_folder_format(fmt or getattr(self.config, "folder_format", None) or DEFAULT_FOLDER_FORMAT)
        if ftype == FileType.IMAGE:
            dt = photo_date(file_path)  # EXIF date taken, else modified time
        else:
            dt = datetime.fromtimestamp(file_path.stat().st_mtime)
        name = fmt.replace("{type}", ftype.value.title())
        return dt.strftime(name.replace("{", "").replace("}", ""))
