#!/usr/bin/env python3
"""Shared path helpers for the paper-search workflow."""
from __future__ import annotations

import os
from pathlib import Path

PDF_ROOT_ENV_VARS = ("PHD_BUYYA_DIR", "PAPER_PDF_DIR")


def _expand(value: str) -> Path:
    return Path(value).expanduser().resolve()


def pdf_root_candidates(repo_dir: Path | None = None) -> list[Path]:
    """Return possible PHD-Buyya locations, in priority order.

    Supports both layouts:
    - server/current workflow: workspace/PHD-Buyya next to the repo
    - local Mac clone: repo/PHD-Buyya inside the repo folder
    """
    repo_dir = (repo_dir or Path(__file__).resolve().parents[1]).resolve()
    candidates: list[Path] = []
    for env_name in PDF_ROOT_ENV_VARS:
        raw = os.getenv(env_name, "").strip()
        if raw:
            candidates.append(_expand(raw))
    candidates.extend([
        repo_dir.parent / "PHD-Buyya",
        repo_dir / "PHD-Buyya",
        Path.cwd() / "PHD-Buyya",
    ])

    seen: set[Path] = set()
    out: list[Path] = []
    for path in candidates:
        path = path.resolve()
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def find_pdf_root(repo_dir: Path | None = None, create: bool = False) -> Path:
    """Find the active PDF root.

    Existing candidates win. If none exists, return/create the default sibling
    folder next to the repo to preserve the server workflow.
    """
    for env_name in PDF_ROOT_ENV_VARS:
        raw = os.getenv(env_name, "").strip()
        if raw:
            root = _expand(raw)
            if create:
                root.mkdir(parents=True, exist_ok=True)
            return root

    candidates = pdf_root_candidates(repo_dir)
    for path in candidates:
        if path.exists():
            return path
    root = candidates[0]
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root
