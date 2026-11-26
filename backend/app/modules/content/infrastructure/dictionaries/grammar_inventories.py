"""Grammar inventory readers: item reference -> framework level, nothing else.

Only the item number and its level are read; the inventory's own descriptions are not
imported, because DeepLingo writes its explanations and examples itself.
"""
from __future__ import annotations

import csv
import re

HSK_BAND_7_9 = "HSK7"  # GF 0025-2021 lists levels 7-9 as one band


def load_gf0025_grammar(path: str) -> dict[str, str]:
    """HSK 3.0 grammar syllabus (GF 0025-2021) as extracted by ivankra/hsk30 (`No`, `Level`)."""
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not {"No", "Level"} <= set(rows[0]):
        raise ValueError("expected a GF 0025-2021 grammar CSV with No and Level columns")
    return {row["No"].strip(): hsk_level(row["Level"]) for row in rows if row["No"].strip()}


def hsk_level(value: str) -> str:
    value = value.strip()
    if value == "7-9":
        return HSK_BAND_7_9
    if value.isdigit() and 1 <= int(value) <= 6:
        return f"HSK{value}"
    raise ValueError(f"unknown HSK level {value!r}")


_CEFR = re.compile(r"(A1|A2|B1|B2|C1|C2)")


def load_cefrj_grammar(path: str) -> dict[str, str | None]:
    """CEFR-J Grammar Profile 20180315 (`ID` -> CEFR level, or None when CEFR-J gives none).

    Only CEFR-J's own columns are read: `CEFR-J Level` (A1.1 -> A1), else `FREQ*DISP`
    (A2-B1 -> A2). The file also carries Core Inventory, EGP and GSELO levels; those belong
    to other publishers (EGP forbids commercial use) and are deliberately ignored.
    """
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not {"ID", "CEFR-J Level", "FREQ*DISP"} <= set(rows[0]):
        raise ValueError("expected the CEFR-J Grammar Profile CSV with ID, CEFR-J Level and FREQ*DISP")
    levels: dict[str, str | None] = {}
    for row in rows:
        item = row["ID"].strip()
        if not item:
            continue
        match = _CEFR.search(row["CEFR-J Level"]) or _CEFR.search(row["FREQ*DISP"])
        levels[item] = match.group(1) if match else None
    return levels
