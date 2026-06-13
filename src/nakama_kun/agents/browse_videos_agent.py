"""Agent responsible for browsing the user's Videos folder and reporting its contents."""

import os
import platform
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from nakama_kun.utils.file_helpers import get_home_dir, format_size, get_video_extensions


def get_videos_folder_path() -> Optional[Path]:
    """Detect and return the path to the user's Videos folder."""
    home = get_home_dir()
    if not home:
        return None
    system = platform.system()
    if system == "Windows":
        # Windows: typically under user profile, e.g. C:\Users\username\Videos
        videos_path = Path(os.environ.get("USERPROFILE", home)) / "Videos"
    elif system == "Darwin":
        # macOS
        videos_path = Path(home) / "Movies"
    else:
        # Linux and other Unix-like
        videos_path = Path(home) / "Videos"
    if videos_path.exists() and videos_path.is_dir():
        return videos_path
    return None


def list_videos(
    folder_path: Path, extensions: Optional[List[str]] = None, recursive: bool = False
) -> List[Dict[str, object]]:
    """List video files in the given folder.
    Returns a list of dicts with 'name', 'path', 'size', 'modified' keys.
    """
    if extensions is None:
        extensions = get_video_extensions()
    video_files = []
    # Use rglob if recursive, else glob
    pattern = "**/*" if recursive else "*"
    for item in folder_path.glob(pattern):
        if item.is_file() and item.suffix.lower() in extensions:
            stat_info = item.stat()
            video_files.append(
                {
                    "name": item.name,
                    "path": str(item.relative_to(folder_path)),
                    "size": stat_info.st_size,
                    "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                }
            )
    return video_files


def generate_report(video_files: List[Dict[str, object]], folder_path: Path) -> str:
    """Generate a human-readable summary report of video files."""
    if not video_files:
        return f"The folder '{folder_path}' contains no video files."
    total_size = sum(f["size"] for f in video_files)
    count = len(video_files)
    modifications = [f["modified"] for f in video_files]
    oldest = min(modifications)
    newest = max(modifications)
    report_lines = [f"## Videos Folder: {folder_path}", ""]
    report_lines.append(f"Total video files: {count}")
    report_lines.append(f"Total size: {format_size(total_size)}")
    report_lines.append(f"Oldest modification: {oldest}")
    report_lines.append(f"Newest modification: {newest}")
    report_lines.append("")
    report_lines.append("### Details")
    report_lines.append("| # | Filename | Size | Modified |")
    report_lines.append("|---|----------|------|----------|")
    for i, file_info in enumerate(video_files, start=1):
        report_lines.append(
            f"| {i} | {file_info['name']} | {format_size(file_info['size'])} | {file_info['modified']} |"
        )
    return "\n".join(report_lines)


def browse_videos(recursive: bool = False) -> str:
    """Main function to browse Videos folder and return a report."""
    folder = get_videos_folder_path()
    if folder is None:
        return "Error: Could not locate the Videos folder. The folder may not exist or be accessible."
    video_files = list_videos(folder, recursive=recursive)
    return generate_report(video_files, folder)
