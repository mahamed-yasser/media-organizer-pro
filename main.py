"""Main entry point for Media Organizer Pro."""

import argparse
import logging
from pathlib import Path
from typing import Optional
import sys
import shutil
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from logger import setup_logger
from config import Config
from organizer import MediaOrganizer, FileType
from video_processor import VideoProcessor
from audio_processor import AudioProcessor
from image_processor import ImageProcessor
from classifier import MediaClassifier
from tools import (DuplicateIndex, photo_date, save_undo_run, undo_last_run, write_report)

def unique_destination(dest_dir: Path, name: str) -> Path:
    """Return a path in dest_dir that does not exist yet (adds _1, _2 ... before the extension)."""
    dest = dest_dir / name
    stem, suffix, i = Path(name).stem, Path(name).suffix, 1
    while dest.exists():
        dest = dest_dir / f"{stem}_{i}{suffix}"
        i += 1
    return dest


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Media Organizer Pro - Intelligent media file organization tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --source ./Downloads --target ./Organized
  python main.py --source ./Videos --config config.yaml --dry-run
  python main.py --recursive --verbose
        """
    )

    parser.add_argument('--source', '-s', help='Source directory to organize (not needed with --undo)')
    parser.add_argument('--target', '-t', default=None, help='Target directory for organized files')
    parser.add_argument('--config', '-c', help='Path to YAML configuration file')
    parser.add_argument('--dry-run', '-d', action='store_true', help='Simulate without moving files')
    parser.add_argument('--recursive', '-r', action='store_true', default=True, help='Search sub-folders (default, kept for compatibility)')
    parser.add_argument('--no-recursive', dest='recursive', action='store_false', help='Only look at the top level of the source folder')
    parser.add_argument('--folder-format', help='Folder layout inside the target, e.g. "{type}/{%%Y}/{%%B}" (default), "{%%Y}/{%%m}/{type}" or "{type}"')
    parser.add_argument('--copy', action='store_true', help='Copy files instead of moving them')
    parser.add_argument('--dedupe', action='store_true', help='Skip files whose content is identical to one already in the target')
    parser.add_argument('--undo', action='store_true', help='Undo the last run that wrote into --target')
    parser.add_argument('--report', metavar='FILE', help='Write a JSON report of every file and what happened to it')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--max-size', '-m', type=int, default=10240, help='Max file size in MB')
    parser.add_argument('--skip-existing', action='store_true', help='Skip files that already exist in target')
    parser.add_argument('--stats', action='store_true', help='Show statistics after organization')

    return parser.parse_args()

def main():
    """Main execution function."""
    args = parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logger = setup_logger('media-organizer', level=log_level)

    if args.undo:
        if not args.target:
            logger.error("--undo needs --target (the folder the files were organized into)")
            return 1
        restored, skipped = undo_last_run(Path(args.target))
        logger.info(f"Undo: restored {restored} files, skipped {skipped}")
        return 0
    if not args.source:
        logger.error("--source is required")
        return 1

    # Load configuration
    try:
        if args.config:
            config = Config.from_yaml(Path(args.config))
            logger.info(f"Loaded configuration from {args.config}")
        else:
            config = Config(
                source_dir=args.source,
                target_dir=args.target or f"./{Path(args.source).name}_organized",
                dry_run=args.dry_run,
                recursive=args.recursive,
                max_file_size_mb=args.max_size
            )
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return 1

    config.dry_run = config.dry_run or args.dry_run
    if args.folder_format:
        config.folder_format = args.folder_format
    args.skip_existing = args.skip_existing or config.skip_existing
    try:
        config.validate()
    except ValueError as e:
        logger.error(f"Invalid configuration: {e}")
        return 1
    if not args.recursive:
        config.recursive = False

    # Validate source directory
    source_path = Path(config.source_dir)
    if not source_path.exists():
        logger.error(f"Source directory does not exist: {source_path}")
        return 1

    if not source_path.is_dir():
        logger.error(f"Source path is not a directory: {source_path}")
        return 1

    # Create target directory if it doesn't exist
    target_path = Path(config.target_dir)
    if not config.dry_run:
        target_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Target directory: {target_path}")

    # Initialize processors
    video_processor = VideoProcessor(config.ffmpeg_path)
    audio_processor = AudioProcessor()
    image_processor = ImageProcessor()
    organizer = MediaOrganizer(config)
    classifier = MediaClassifier()

    # Statistics
    stats = {
        'total_files': 0,
        'videos': 0,
        'images': 0,
        'audios': 0,
        'documents': 0,
        'errors': 0,
        'moved': 0,
        'planned': 0,
        'skipped': 0,
        'duplicates': 0
    }
    undo_moves, actions = [], []
    dupes = DuplicateIndex(target_path) if args.dedupe else None

    logger.info(f"Starting media organization...")
    logger.info(f"Source: {source_path}")
    logger.info(f"Target: {target_path}")
    if config.dry_run:
        logger.warning("DRY RUN MODE - No files will be moved")

    # Process files
    search_pattern = '**/*' if config.recursive else '*'
    for file_path in list(source_path.glob(search_pattern)):
        if not file_path.is_file() or file_path.is_symlink():
            continue  # folders, and symbolic links (never followed or moved)
        try:
            file_path.resolve().relative_to(target_path.resolve())
            continue  # already inside the target folder
        except ValueError:
            pass

        stats['total_files'] += 1

        # Check file size
        if file_path.stat().st_size > config.max_file_size_mb * 1024 * 1024:
            logger.warning(f"Skipping large file (> {config.max_file_size_mb}MB): {file_path.name}")
            stats['skipped'] += 1
            continue

        # Classify file
        file_type = organizer.classify_file(file_path)
        if file_type == FileType.UNKNOWN:
            continue

        try:
            # Get detailed info
            if file_type == FileType.VIDEO:
                info = video_processor.probe_video(file_path)
                stats['videos'] += 1
                if info:
                    logger.debug(f"Video: {file_path.name} - {info.resolution_str} @ {info.duration_str}")

            elif file_type == FileType.AUDIO:
                info = audio_processor.probe_audio(file_path)
                stats['audios'] += 1
                if info:
                    logger.debug(f"Audio: {file_path.name} - {info.duration_str} - {info.quality_label}")

            elif file_type == FileType.DOCUMENT:
                stats['documents'] += 1

            elif file_type == FileType.IMAGE:
                info = image_processor.probe_image(file_path)
                stats['images'] += 1
                if info:
                    logger.debug(f"Image: {file_path.name} - {info.resolution_str}")

            # Organize: move the file (or only log it in dry-run mode)
            if dupes is not None:
                original = dupes.original_of(file_path)
                if original is not None:
                    stats['duplicates'] += 1
                    actions.append({'file': str(file_path), 'action': 'duplicate', 'same_as': str(original)})
                    logger.info(f"Duplicate skipped: {file_path.name} (same content as {original.name})")
                    continue
            dest_dir = target_path / organizer.generate_folder_name(file_path, file_type)
            dest = unique_destination(dest_dir, file_path.name)
            if args.skip_existing and (dest_dir / file_path.name).exists():
                stats['skipped'] += 1
                continue
            if config.dry_run:
                logger.info(f"[dry-run] {file_path} -> {dest}")
                stats['planned'] += 1
                actions.append({'file': str(file_path), 'action': 'planned', 'to': str(dest)})
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                (shutil.copy2 if args.copy else shutil.move)(str(file_path), str(dest))
                logger.debug(f"{'Copied' if args.copy else 'Moved'} {file_path.name} -> {dest}")
                stats['moved'] += 1
                entry = {'from': str(file_path), 'to': str(dest), 'copy': args.copy}
                if args.copy:
                    st = dest.stat()
                    entry.update(size=st.st_size, mtime_ns=st.st_mtime_ns)
                undo_moves.append(entry)
                actions.append({'file': str(file_path), 'action': 'copied' if args.copy else 'moved', 'to': str(dest)})

        except Exception as e:
            # a move across folders is copy + delete: if the delete failed, remove our copy
            # so the file does not end up in two places
            try:
                if not args.copy and not config.dry_run and 'dest' in locals() and dest.exists() and file_path.exists():
                    dest.unlink()
            except OSError:
                pass
            logger.error(f"Error processing {file_path.name}: {e}")
            stats['errors'] += 1

    # Print statistics
    if stats['total_files'] > 0 or args.stats:
        logger.info("=" * 50)
        logger.info("ORGANIZATION STATISTICS")
        logger.info("=" * 50)
        logger.info(f"Total files scanned: {stats['total_files']}")
        logger.info(f"Videos:     {stats['videos']}")
        logger.info(f"Images:     {stats['images']}")
        logger.info(f"Audios:     {stats['audios']}")
        logger.info(f"Documents:  {stats['documents']}")
        logger.info(f"Planned (dry-run): {stats['planned']}")
        logger.info(f"Moved:      {stats['moved']}")
        logger.info(f"Skipped:    {stats['skipped']}")
        logger.info(f"Duplicates: {stats['duplicates']}")
        logger.info(f"Errors:     {stats['errors']}")
        logger.info("=" * 50)

    if not config.dry_run:
        save_undo_run(target_path, undo_moves)
    if args.report:
        write_report(Path(args.report), stats, actions)
        logger.info(f"Report written to {args.report}")
    if stats['errors']:
        logger.error(f"Finished with {stats['errors']} error(s); see messages above")
        return 1
    logger.info("Organization completed successfully!")
    return 0

if __name__ == '__main__':
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
