"""Daily spending cap and usage counter, persisted as JSON (stdlib only)."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable

WARN_FRACTION = 0.8


class Budget:
    def __init__(
        self,
        path: Path,
        cap_usd: float | None,
        price_in_per_mtok: float,
        price_out_per_mtok: float,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._path = path
        self.cap_usd = cap_usd
        self._price_in = price_in_per_mtok
        self._price_out = price_out_per_mtok
        self._clock = clock

    def _today(self) -> str:
        return self._clock().strftime("%Y-%m-%d")

    def _load(self) -> dict:
        fresh = {"date": self._today(), "input": 0, "output": 0, "cost": 0.0, "calls": 0, "warned": False}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return fresh
        return data if data.get("date") == fresh["date"] else fresh

    def _save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def spent_today(self) -> float:
        return float(self._load()["cost"])

    def can_spend(self) -> bool:
        return self.cap_usd is None or self.spent_today() < self.cap_usd

    def add(self, input_tokens: int, output_tokens: int) -> float:
        """Record one call and return its cost in USD."""
        cost = input_tokens * self._price_in / 1e6 + output_tokens * self._price_out / 1e6
        data = self._load()
        data["input"] += input_tokens
        data["output"] += output_tokens
        data["cost"] += cost
        data["calls"] += 1
        self._save(data)
        return cost

    def should_warn(self) -> bool:
        """True once per day, the first time spending crosses 80% of the cap."""
        if not self.cap_usd:
            return False
        data = self._load()
        if data["warned"] or data["cost"] < WARN_FRACTION * self.cap_usd:
            return False
        data["warned"] = True
        self._save(data)
        return True

    def summary(self) -> str:
        data = self._load()
        cap = f"US$ {self.cap_usd:.2f}" if self.cap_usd is not None else "sem teto"
        return (
            f"Hoje: {data['calls']} chamadas, {data['input']} tokens de entrada, "
            f"{data['output']} de saída, US$ {data['cost']:.4f} (teto: {cap})."
        )
