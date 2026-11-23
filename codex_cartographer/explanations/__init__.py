"""Explanation layer public API."""

from codex_cartographer.explanations.generator import (
    ExplanationBackend,
    StructuralExplanationBackend,
    attach_explanations,
    explain_edge,
)

__all__ = [
    "ExplanationBackend",
    "StructuralExplanationBackend",
    "attach_explanations",
    "explain_edge",
]
