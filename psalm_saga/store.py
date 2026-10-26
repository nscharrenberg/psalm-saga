"""A run directory: every artifact as a readable file, written atomically.

    runs/<run-id>/
      run.json            config snapshot, status, usage, timings
      events.jsonl        every pipeline/LLM event (for the CLI, web app and audits)
      input/source.txt | input/premise.md | input/spec.json
      profile.json, notes/chunk_000.json, bible_source.json, spec_source.json,
      transform.json, spec.json, bible.json, plan.json,
      chapters/ch_001.json, reviews/ch_001.json, story.md, story.json, evaluation.json
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


_CRLF = re.compile(r"\r+\n")


def normalize_newlines(text: str) -> str:
    """CRLF, CR CR LF (a CRLF text written in text mode on Windows) and lone CR all become LF."""
    return _CRLF.sub("\n", text).replace("\r", "\n") if "\r" in text else text


class RunStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.listeners: list[Callable[[dict], None]] = []

    @property
    def id(self) -> str:
        return self.root.name

    def path(self, name: str) -> Path:
        return self.root / name

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def write_text(self, name: str, text: str) -> Path:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        # newline="\n": never translate line endings. In text mode on Windows "\n" becomes "\r\n",
        # so a CRLF upload was stored as "\r\r\n" and read back with a blank line after every line.
        tmp.write_text(normalize_newlines(text), encoding="utf-8", newline="\n")
        tmp.replace(p)
        return p

    def read_text(self, name: str) -> str:
        with open(self.path(name), encoding="utf-8", newline="") as fh:  # raw, then normalised
            return normalize_newlines(fh.read())

    def write_json(self, name: str, obj: BaseModel | dict | list) -> Path:
        data = obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj
        return self.write_text(name, json.dumps(data, ensure_ascii=False, indent=2))

    def read_json(self, name: str, model: type[T] | None = None) -> Any:
        data = json.loads(self.read_text(name))
        return model.model_validate(data) if model else data

    def maybe(self, name: str, model: type[T]) -> T | None:
        return self.read_json(name, model) if self.exists(name) else None

    def glob(self, pattern: str) -> list[Path]:
        return sorted(self.root.glob(pattern))

    def delete(self, pattern: str) -> None:
        for p in self.root.glob(pattern):
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)

    # ----------------------------------------------------------------- events

    def emit(self, event: dict) -> None:
        event = {"ts": round(time.time(), 3), **event}
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._lock, open(self.path("events.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        for fn in list(self.listeners):
            try:
                fn(event)
            except Exception:
                pass

    def events(self, since: int = 0) -> list[dict]:
        if not self.exists("events.jsonl"):
            return []
        lines = self.read_text("events.jsonl").splitlines()
        return [json.loads(x) for x in lines[since:] if x.strip()]

    # ----------------------------------------------------------------- run meta

    def meta(self) -> dict:
        return self.read_json("run.json") if self.exists("run.json") else {}

    def update_meta(self, **kw) -> dict:
        with self._lock:
            m = self.meta()
            m.update(kw)
            self.write_json("run.json", m)
        return m
