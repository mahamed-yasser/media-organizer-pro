"""Configuration manager for Media Organizer Pro."""

import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_FOLDER_FORMAT = "{type}/{%Y}/{%B}"
_ALLOWED_DATE = {"%Y", "%m", "%B", "%b", "%d"}


def validate_folder_format(fmt: str) -> str:
    """Return fmt if it only uses {type} and {%Y} {%m} {%B} {%b} {%d}; raise ValueError otherwise."""
    import re
    if not isinstance(fmt, str) or not fmt.strip():
        raise ValueError("folder_format must be a non-empty text")
    if fmt.startswith(("/", "\\")) or ".." in fmt.replace("\\", "/").split("/") or ":" in fmt:
        raise ValueError(f"folder_format must be a relative path inside the target folder: {fmt!r}")
    for tok in re.findall(r"\{([^}]*)\}", fmt):
        if tok != "type" and tok not in _ALLOWED_DATE:
            raise ValueError(f"folder_format: unsupported placeholder {{{tok}}} (allowed: {{type}} and "
                             + " ".join("{" + d + "}" for d in sorted(_ALLOWED_DATE)) + ")")
    if re.sub(r"\{[^}]*\}", "", fmt).count("{") or fmt.count("}") != fmt.count("{"):
        raise ValueError(f"folder_format has unbalanced braces: {fmt!r}")
    return fmt


@dataclass
class Config:
    source_dir: str = "./input"
    target_dir: str = "./output"
    video_extensions: list[str] = field(default_factory=lambda: ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'])
    image_extensions: list[str] = field(default_factory=lambda: ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'])
    audio_extensions: list[str] = field(default_factory=lambda: ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma'])
    document_extensions: list[str] = field(default_factory=lambda: ['.pdf', '.doc', '.docx', '.txt', '.xls', '.xlsx'])
    use_ml_classification: bool = False
    ffmpeg_path: Optional[str] = None
    dry_run: bool = False
    recursive: bool = True
    max_file_size_mb: int = 10240
    folder_format: str = DEFAULT_FOLDER_FORMAT
    skip_existing: bool = False
    model_path: Optional[str] = None

    @classmethod
    def from_yaml(cls, path: Path) -> 'Config':
        """Load configuration from YAML file."""
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"{path} is not a YAML mapping of settings")
        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"Unknown setting(s) in {path}: {', '.join(unknown)}. Known: {', '.join(sorted(known))}")
        cfg = cls(**data)
        cfg.validate()
        return cfg

    def validate(self):
        validate_folder_format(self.folder_format)

    def to_dict(self) -> dict:
        """Convert config to dictionary."""
        return {
            'source_dir': self.source_dir,
            'target_dir': self.target_dir,
            'video_extensions': self.video_extensions,
            'image_extensions': self.image_extensions,
            'audio_extensions': self.audio_extensions,
            'document_extensions': self.document_extensions,
            'use_ml_classification': self.use_ml_classification,
            'ffmpeg_path': self.ffmpeg_path,
            'dry_run': self.dry_run,
            'recursive': self.recursive,
            'max_file_size_mb': self.max_file_size_mb,
            'folder_format': self.folder_format,
            'skip_existing': self.skip_existing,
        }
