from __future__ import annotations

import csv
import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from html.parser import HTMLParser
from typing import Any, Iterable


CONFIG_NAME = ".kgnite.json"
SCORE_KEYS = ("publicScore", "privateScore", "score")
DATE_KEYS = ("date", "submittedAt", "submissionDate", "createdAt")
PREVIEWABLE_SUFFIXES = {".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".txt"}
SAFE_NOTE_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}


class CompetitionNotesSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "iframe", "object"}:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in SAFE_NOTE_TAGS:
            return
        rendered_attrs = ""
        if tag == "a":
            href = next(
                (value for key, value in attrs if key.casefold() == "href"), None
            )
            if href and href.startswith(("https://", "http://")):
                rendered_attrs = (
                    f' href="{html.escape(href, quote=True)}" target="_blank"'
                )
        self.parts.append(f"<{tag}{rendered_attrs}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "iframe", "object"}:
            self.blocked_depth = max(0, self.blocked_depth - 1)
            return
        if not self.blocked_depth and tag in SAFE_NOTE_TAGS and tag != "br":
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.parts.append(html.escape(data))


def sanitize_competition_notes(content: str) -> str:
    sanitizer = CompetitionNotesSanitizer()
    sanitizer.feed(content)
    sanitizer.close()
    return "".join(sanitizer.parts).strip()


def filter_resource_rows(
    rows: list[dict[str, str]],
    *,
    tags: Iterable[str] = (),
    keywords: Iterable[str] = (),
) -> list[dict[str, str]]:
    """Filter Kaggle CSV rows without relying on resource-specific column names."""
    wanted_tags = [value.casefold() for value in tags if value]
    wanted_keywords = [value.casefold() for value in keywords if value]
    filtered: list[dict[str, str]] = []
    for row in rows:
        searchable = " ".join(str(value) for value in row.values()).casefold()
        if wanted_tags and not all(tag in searchable for tag in wanted_tags):
            continue
        if wanted_keywords and not all(
            keyword in searchable for keyword in wanted_keywords
        ):
            continue
        filtered.append(row)
    return filtered


def choose_preview_file(
    files: list[dict[str, Any]],
    requested_path: str | None = None,
    *,
    max_bytes: int,
) -> tuple[str, int | None]:
    normalized: list[tuple[str, int | None]] = []
    for item in files:
        name = str(item.get("name") or item.get("ref") or item.get("fileName") or "")
        try:
            size = int(item.get("size")) if item.get("size") not in (None, "") else None
        except (TypeError, ValueError):
            size = None
        if name:
            normalized.append((name, size))
    if requested_path:
        match = next((item for item in normalized if item[0] == requested_path), None)
        if match is None:
            raise ValueError(f"Dataset file was not found: {requested_path}")
        candidates = [match]
    else:
        candidates = [
            item
            for item in normalized
            if Path(item[0]).suffix.lower() in PREVIEWABLE_SUFFIXES
        ]
        candidates.sort(
            key=lambda item: (
                "sample" in item[0].casefold(),
                item[1] is None,
                item[1] or 0,
                item[0].casefold(),
            )
        )
    if not candidates:
        supported = ", ".join(sorted(PREVIEWABLE_SUFFIXES))
        raise ValueError(
            f"No previewable file found. Supported file types: {supported}"
        )
    name, size = candidates[0]
    suffix = Path(name).suffix.lower()
    if suffix not in PREVIEWABLE_SUFFIXES:
        supported = ", ".join(sorted(PREVIEWABLE_SUFFIXES))
        raise ValueError(
            f"File type `{suffix or 'unknown'}` cannot be previewed. Supported: {supported}"
        )
    if size is not None and size > max_bytes:
        raise ValueError(
            f"Selected file is {size / 1024 / 1024:.1f} MB, above the preview limit of "
            f"{max_bytes / 1024 / 1024:.1f} MB. Choose a smaller --path or raise --max-file-size-mb."
        )
    return name, size


def preview_local_file(
    path: Path, *, row_limit: int, column_limit: int | None
) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
            reader = csv.DictReader(handle, delimiter="\t" if suffix == ".tsv" else ",")
            all_fields = reader.fieldnames or []
            fields = all_fields if column_limit is None else all_fields[:column_limit]
            rows: list[dict[str, Any]] = []
            total_rows = 0
            for row in reader:
                if total_rows < row_limit:
                    rows.append({field: row.get(field, "") for field in fields})
                total_rows += 1
            return _preview_result(rows, total_rows, all_fields)
    if suffix in {".jsonl", ".ndjson"}:
        rows: list[dict[str, Any]] = []
        total_rows = 0
        all_columns: list[str] = []
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                value = json.loads(line)
                full_row = _preview_row(value, None)
                for column in full_row:
                    if column not in all_columns:
                        all_columns.append(column)
                if total_rows < row_limit:
                    rows.append(_preview_row(value, column_limit))
                total_rows += 1
        return _preview_result(rows, total_rows, all_columns)
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        values = value if isinstance(value, list) else [value]
        all_columns: list[str] = []
        for item in values:
            for column in _preview_row(item, None):
                if column not in all_columns:
                    all_columns.append(column)
        rows = [_preview_row(item, column_limit) for item in values[:row_limit]]
        return _preview_result(rows, len(values), all_columns)
    if suffix == ".txt":
        with path.open(encoding="utf-8", errors="replace") as handle:
            rows = []
            total_rows = 0
            for line in handle:
                if total_rows < row_limit:
                    rows.append({"line": total_rows + 1, "text": line.rstrip("\n")})
                total_rows += 1
            return _preview_result(rows, total_rows, ["line", "text"])
    raise ValueError(f"Unsupported preview file type: {suffix}")


def _preview_row(value: Any, column_limit: int | None) -> dict[str, Any]:
    if isinstance(value, dict):
        items = list(value.items())
        return dict(items if column_limit is None else items[:column_limit])
    return {"value": value}


def _preview_result(
    rows: list[dict[str, Any]], total_rows: int, columns: list[str]
) -> dict[str, Any]:
    return {
        "rows": rows,
        "shape": {"rows": total_rows, "columns": len(columns)},
        "columns": columns,
        "displayed_rows": len(rows),
        "displayed_columns": len(rows[0]) if rows else min(len(columns), 0),
    }


def create_competition_workspace(
    competition: str,
    directory: Path,
    *,
    metric: str = "publicScore",
    lower_is_better: bool = False,
    participant: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    directory = directory.expanduser().resolve()
    config_path = directory / CONFIG_NAME
    if config_path.exists() and not force:
        raise FileExistsError(f"Workspace already exists: {config_path}")
    for child in ("data", "notebooks", "submissions"):
        (directory / child).mkdir(parents=True, exist_ok=True)
    config = {
        "competition": competition,
        "metric": metric,
        "lower_is_better": lower_is_better,
        "participant": participant,
        "data_dir": "data",
        "notebook_dir": "notebooks",
        "submission_dir": "submissions",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    return {"directory": str(directory), "config": str(config_path), **config}


def discover_sample_columns(data_dir: Path) -> list[str]:
    candidates = sorted(data_dir.glob("**/*sample*submission*.csv"))
    if not candidates:
        return []
    with candidates[0].open(newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle), [])


def starter_notebook(
    competition: str,
    data_dir: str,
    columns: list[str],
    *,
    participant: str,
    competition_notes: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    column_note = (
        ", ".join(columns)
        if columns
        else "detected from sample_submission.csv at runtime"
    )
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                f"# {competition} starter notebook\n",
                f"**Participant:** {participant}\n\n",
                "Personal competition workspace for analysis, experimentation, and submission development.\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from pathlib import Path\n",
                "import pandas as pd\n",
                f"DATA_DIR = Path({data_dir!r})\n",
                "files = sorted(DATA_DIR.glob('**/*'))\n",
                "[str(path) for path in files if path.is_file()][:20]\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Load competition data\n",
                f"Expected submission columns: `{column_note}`\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "def find_csv(fragment):\n",
                "    matches = list(DATA_DIR.glob(f'**/*{fragment}*.csv'))\n",
                "    return pd.read_csv(matches[0]) if matches else None\n",
                "\n",
                "train = find_csv('train')\n",
                "test = find_csv('test')\n",
                "sample_submission = find_csv('sample_submission')\n",
                "[(name, None if frame is None else frame.shape) for name, frame in "
                "[('train', train), ('test', test), ('sample_submission', sample_submission)]]\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Baseline\n",
                "Add preprocessing, validation, and model training here.\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# Replace this copy with model predictions.\n",
                "if sample_submission is not None:\n",
                "    output = Path('submission.csv')\n",
                "    sample_submission.to_csv(output, index=False)\n",
                "    print(f'Wrote {output} with shape {sample_submission.shape}')\n",
            ],
        },
    ]
    for note in reversed(competition_notes or []):
        name = note.get("name", "competition-notes")
        source_url = note.get(
            "url", f"https://www.kaggle.com/competitions/{competition}"
        )
        content = sanitize_competition_notes(note.get("content", ""))
        cells.insert(
            1,
            {
                "cell_type": "markdown",
                "metadata": {"kgnite_note_page": name},
                "source": [
                    f"## Competition notes: {name}\n\n",
                    f"Source: [Kaggle competition page]({source_url})\n\n",
                    content,
                ],
            },
        )
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3"},
            "kgnite": {"competition": competition, "participant": participant},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def write_starter_notebook(
    competition: str,
    output: Path,
    data_dir: Path,
    *,
    participant: str,
    competition_notes: list[dict[str, str]] | None = None,
    force: bool = False,
) -> Path:
    output = output.expanduser().resolve()
    if output.exists() and not force:
        raise FileExistsError(f"Notebook already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = discover_sample_columns(data_dir.expanduser().resolve())
    notebook = starter_notebook(
        competition,
        str(data_dir),
        columns,
        participant=participant,
        competition_notes=competition_notes,
    )
    output.write_text(json.dumps(notebook, indent=2) + "\n")
    return output


def _first(row: dict[str, Any], keys: Iterable[str]) -> Any:
    lower = {key.casefold(): value for key, value in row.items()}
    for key in keys:
        value = lower.get(key.casefold())
        if value not in (None, ""):
            return value
    return None


def normalize_scores(
    rows: list[dict[str, Any]], competition: str
) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        raw_score = _first(row, SCORE_KEYS)
        if raw_score in (None, ""):
            continue
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        normalized.append(
            {
                "competition": competition,
                "date": str(_first(row, DATE_KEYS) or ""),
                "score": score,
                "public_score": _first(row, ("publicScore",)),
                "private_score": _first(row, ("privateScore",)),
                "description": str(
                    _first(row, ("description", "message", "fileName", "ref")) or ""
                ),
            }
        )
    return normalized


def merge_score_history(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in [*existing, *incoming]:
        key = (
            row.get("competition"),
            row.get("date"),
            row.get("score"),
            row.get("description"),
        )
        merged[key] = row
    return sorted(merged.values(), key=lambda row: str(row.get("date", "")))


def load_score_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("Score history must be a JSON array")
    return data


def save_score_history(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2) + "\n")


def score_sparkline(scores: list[float]) -> str:
    if not scores:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    low, high = min(scores), max(scores)
    if math.isclose(low, high):
        return blocks[len(blocks) // 2] * len(scores)
    return "".join(
        blocks[round((score - low) / (high - low) * (len(blocks) - 1))]
        for score in scores
    )
