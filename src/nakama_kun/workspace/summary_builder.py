from __future__ import annotations

from pathlib import Path
from nakama_kun.workspace.models import ProjectSnapshot


class WorkspaceSummaryBuilder:
    """Builder that converts a ProjectSnapshot into a structured Markdown summary."""

    @staticmethod
    def build_summary(snapshot: ProjectSnapshot) -> str:
        """Construct the project summary text based on the snapshot values."""
        # 1. Project Type heuristics
        project_type = "Unknown"
        file_set = {Path(f).name for f in snapshot.files}
        
        if "pyproject.toml" in file_set or "requirements.txt" in file_set:
            project_type = "Python Project"
        elif "package.json" in file_set:
            # Let's see if typescript is present in dependencies or extension exists
            has_ts = any("typescript" in dep.lower() for dep in snapshot.dependencies) or any(
                f.endswith(".ts") or f.endswith(".tsx") for f in snapshot.files
            )
            project_type = "TypeScript Project" if has_ts else "JavaScript Project"
        elif "Cargo.toml" in file_set:
            project_type = "Rust Project"
        else:
            # Fall back to dominant language based on file counts
            if snapshot.languages:
                dominant_lang = max(snapshot.languages, key=snapshot.languages.get)  # type: ignore
                project_type = f"{dominant_lang} Project"

        # 2. Languages formatting
        total_files = len(snapshot.files)
        lang_strs = []
        if snapshot.languages:
            # Sort languages by file count in descending order
            sorted_langs = sorted(snapshot.languages.items(), key=lambda x: -x[1])
            for lang, count in sorted_langs:
                percentage = (count / total_files) * 100 if total_files > 0 else 0
                lang_strs.append(f"{lang} ({count} files, {percentage:.1f}%)")
        languages_str = ", ".join(lang_strs) if lang_strs else "None detected"

        # 3. Dependencies formatting
        dependencies_str = ", ".join(snapshot.dependencies) if snapshot.dependencies else "None detected"

        # 4. Entrypoints formatting
        entrypoints_str = ", ".join(snapshot.entrypoints) if snapshot.entrypoints else "None detected"

        # 5. Test Locations formatting
        test_locs = []
        if snapshot.tests.directories:
            test_locs.append(f"Directories: {', '.join(snapshot.tests.directories)}")
        if snapshot.tests.files:
            test_locs.append(f"Files: {len(snapshot.tests.files)} test files found")
        test_locations_str = " | ".join(test_locs) if test_locs else "None detected"

        # 6. Git Info (optional, but highly descriptive helper)
        git_str = ""
        if snapshot.git_info.commit_hash:
            git_status_desc = "Clean" if snapshot.git_info.status_clean else "Dirty"
            git_str = (
                f"- **Git Status**: Branch `{snapshot.git_info.branch}`, "
                f"Commit `{snapshot.git_info.commit_hash[:7]}`, "
                f"Working Directory: `{git_status_desc}`"
            )

        # Build output lines
        lines = [
            "## Project Workspace Summary",
            f"- **Project Type**: {project_type}",
            f"- **Languages**: {languages_str}",
            f"- **Dependencies**: {dependencies_str}",
            f"- **Entrypoints**: {entrypoints_str}",
            f"- **Test Locations**: {test_locations_str}",
        ]
        if git_str:
            lines.append(git_str)

        return "\n".join(lines)
