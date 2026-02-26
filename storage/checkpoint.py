"""
Checkpoint helper: persists phase progress as JSON so the pipeline can
resume after interruption without re-fetching already-collected data.

Two usage patterns:

1. Keyset-pagination (Phase 1):
   ckpt.get_after_id()         -> str | None
   ckpt.set_after_id(cursor, count)

2. Per-entity completion (Phases 2–4):
   ckpt.is_done(entity_uuid)   -> bool
   ckpt.mark_done(entity_uuid)
   ckpt.get_completed_set()    -> set[str]
"""

import json
import logging
from pathlib import Path
import config

logger = logging.getLogger(__name__)


class Checkpoint:

    def __init__(self, phase_name: str):
        self.path = config.CHECKPOINT_DIR / f"{phase_name}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path) as f:
                data = json.load(f)
            logger.info("Loaded checkpoint %s", self.path.name)
            return data
        return {}

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)

    # -- Keyset pagination -------------------------------------------- #

    def get_after_id(self) -> str | None:
        return self._data.get("after_id")

    def set_after_id(self, after_id: str | None, count: int):
        self._data["after_id"]        = after_id
        self._data["collected_count"] = count
        self._save()

    # -- Per-entity completion ---------------------------------------- #

    def is_done(self, entity_id: str) -> bool:
        return entity_id in self._data.get("completed", [])

    def mark_done(self, entity_id: str):
        self._data.setdefault("completed", [])
        if entity_id not in self._data["completed"]:
            self._data["completed"].append(entity_id)
        self._save()

    def get_completed_set(self) -> set:
        return set(self._data.get("completed", []))
