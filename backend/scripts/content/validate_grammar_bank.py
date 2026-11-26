"""Validate grammar banks offline; --for-release also requires the owner's sample approval.

Run from backend/: python -m scripts.content.validate_grammar_bank bank.json [--for-release]
No settings, credentials, database, network or model provider are loaded.
"""
import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from app.modules.content.domain.grammar_bank import GrammarBank


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def read_bank(path: Path) -> GrammarBank:
    return GrammarBank.model_validate(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+")
    parser.add_argument("--for-release", action="store_true")
    args = parser.parse_args(argv)
    failed = False
    for name in args.files:
        try:
            bank = read_bank(Path(name))
            if args.for_release:
                bank.require_approval()
        except ValidationError as exc:
            print(json.dumps({"file": name, "valid": False,
                              "errors": exc.errors(include_url=False, include_input=False, include_context=False)}))
            failed = True
            continue
        except (OSError, UnicodeError, ValueError) as exc:
            print(json.dumps({"file": name, "valid": False, "error": str(exc)}))
            failed = True
            continue
        print(json.dumps({"file": name, "valid": True, "language": bank.language, "level": bank.level,
                          "support_language": bank.support_language, "topics": len(bank.topics),
                          "points": len(bank.points), "questions": sum(len(point.questions) for point in bank.points),
                          "review": "owner_sample_approved" if bank.approval else "draft",
                          "content_sha256": bank.content_hash()}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
