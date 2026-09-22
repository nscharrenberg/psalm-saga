# ruff: noqa: INP001, T201
"""Build a single self-contained dataset from the stories corpus.

Reads ``data/stories/corpus.csv`` plus the referenced ``.txt`` files under
``data/stories/english`` and ``data/stories/dutch``, embeds each story's full
text as a column, and writes the result to a columnar dataset file (parquet
by default) so downstream consumers never need to touch the raw ``.txt``
files or join against the CSV separately.

Usage::

    uv run python experiments/build_corpus_dataset.py
    uv run python experiments/build_corpus_dataset.py --format feather
    uv run python experiments/build_corpus_dataset.py --output-dir data/stories --format parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

DEFAULT_STORIES_DIR = Path(__file__).resolve().parent / "data" / "stories"
DEFAULT_FILE_NAME = "pilot_corpus"
DEFAULT_CSV_NAME = f"{DEFAULT_FILE_NAME}.csv"


def load_corpus(stories_dir: Path, csv_name: str) -> pd.DataFrame:
    """Load the corpus metadata CSV and embed each story's raw text."""
    csv_path = stories_dir / csv_name
    if not csv_path.exists():
        raise FileNotFoundError(f"corpus CSV not found: {csv_path}")

    # sep=None + engine="python" auto-detects comma vs semicolon (e.g. Excel
    # exports use ';'); utf-8-sig strips a BOM if present, and is otherwise
    # identical to utf-8.
    df = pd.read_csv(csv_path, sep=None, engine="python", encoding="utf-8-sig")

    texts: list[str] = []
    mismatches: list[str] = []
    for row in df.itertuples(index=False):
        story_path = stories_dir / row.path
        if not story_path.exists():
            raise FileNotFoundError(f"story file referenced by '{row.id}' not found: {story_path}")

        text = story_path.read_text(encoding="utf-8")
        texts.append(text)

        actual_words = len(text.split())
        actual_chars = len(text)
        if actual_words != row.word_count or actual_chars != row.char_count:
            mismatches.append(
                f"  {row.id}: csv says words={row.word_count} chars={row.char_count}, "
                f"actual words={actual_words} chars={actual_chars}"
            )

    if mismatches:
        print("Warning: word/char counts in corpus.csv do not match file contents:", file=sys.stderr)
        print("\n".join(mismatches), file=sys.stderr)

    df["text"] = texts
    return df


def write_dataset(df: pd.DataFrame, output_path: Path, fmt: str) -> None:
    """Write the embedded-text dataset to disk in the requested format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "parquet":
        df.to_parquet(output_path, engine="pyarrow", index=False)
    elif fmt == "feather":
        df.to_feather(output_path)
    elif fmt == "csv":
        df.to_csv(output_path, index=False)
    else:
        raise ValueError(f"unsupported format: {fmt}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stories-dir",
        type=Path,
        default=DEFAULT_STORIES_DIR,
        help="Directory containing corpus.csv and the english/dutch story folders.",
    )
    parser.add_argument(
        "--csv-name",
        default=DEFAULT_CSV_NAME,
        help="Name of the corpus metadata CSV file inside --stories-dir.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write the dataset into (defaults to --stories-dir).",
    )
    parser.add_argument(
        "--format",
        choices=["parquet", "feather", "csv"],
        default="parquet",
        help="Output dataset format (default: parquet).",
    )
    parser.add_argument(
        "--filename",
        default=None,
        help="Output filename (defaults to 'corpus.<format-extension>').",
    )
    return parser.parse_args(argv)


EXTENSIONS = {"parquet": "parquet", "feather": "arrow", "csv": "csv"}


def main(argv: list[str] | None = None) -> None:
    """Build and write the embedded-text corpus dataset."""
    args = parse_args(argv)
    stories_dir: Path = args.stories_dir
    output_dir: Path = args.output_dir or stories_dir
    filename = args.filename or f"{DEFAULT_FILE_NAME}.{EXTENSIONS[args.format]}"
    output_path = output_dir / filename

    df = load_corpus(stories_dir, args.csv_name)
    write_dataset(df, output_path, args.format)

    print(f"Wrote {len(df)} stories ({df['text'].str.len().sum():,} chars) to {output_path}")


if __name__ == "__main__":
    main()
