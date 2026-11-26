import json
from functools import lru_cache
from pathlib import Path

from app.modules.content.domain.grammar_bank import GrammarBank

_FILES = {
    "en": ["en/a1.json", "en/a2.json", "en/b1.json", "en/b2.json", "en/c1.json", "en/c2.json"],
    "zh": [f"zh/hsk{level}.json" for level in range(1, 7)],
}


@lru_cache(maxsize=64)
def _read(path: str, modified: int) -> GrammarBank:
    return GrammarBank.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


class GrammarBanks:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parents[4] / "content/grammar_review"

    def for_language(self, language: str, support: str) -> list[GrammarBank]:
        """Banks the owner has approved for this language and support language, lowest level first.

        A draft without approval, or a file that does not exist yet, is skipped: it is never served.
        """
        banks = []
        for name in _FILES.get(language, []):
            path = self.root / name
            if not path.is_file():
                continue
            bank = _read(str(path), path.stat().st_mtime_ns)
            if bank.language != language or bank.support_language != support or bank.approval is None:
                continue
            bank.require_approval()
            banks.append(bank)
        return banks
