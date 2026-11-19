"""Source-file ingestion: walk trees and respect .gitignore."""

from codex_cartographer.ingestion.walker import SourceFile, collect_source_files

__all__ = ["SourceFile", "collect_source_files"]
