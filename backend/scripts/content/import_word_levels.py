"""Record HSK 3.0 (GF 0025-2021) word levels on CC-CEDICT entries.

Dry run by default: matches every HSK word to its CC-CEDICT entry (headword and reading)
and prints counts and examples, writing nothing. Writing requires --apply and
--confirm-project matching the configured Supabase project reference. Re-run after a
CC-CEDICT re-import, which rewrites provider_metadata.

    venv/Scripts/python.exe -m scripts.content.import_word_levels --file D:/deeplingo-dictionaries/zh/hsk30.csv
"""
import argparse
import collections
import json
import sys

from app.modules.content.infrastructure.dictionaries import hsk30
from scripts.content.import_dictionary import project_ref

LOOKUP_BATCH = 200


def main(argv: list[str] | None = None, *, repository=None, settings=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", required=True, help="hsk30.csv from ivankra/hsk30")
    parser.add_argument("--apply", action="store_true", help="write to the configured database")
    parser.add_argument("--confirm-project", default="", help="Supabase project ref that must match configuration")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args(argv)

    words = hsk30.parse_word_levels(args.file)
    if repository is None:
        from app.modules.content.infrastructure.repositories.dictionary_entries import DictionaryEntryRepository
        from app.platform.supabase import supabase_service
        repository = DictionaryEntryRepository(supabase_service)
    headwords = sorted(words)
    rows = []
    for start in range(0, len(headwords), LOOKUP_BATCH):
        rows += repository.list_rows_by_headwords(language_code="zh",
                                                  normalized_headwords=headwords[start:start + LOOKUP_BATCH])
    updated, report = hsk30.apply_levels(rows, words)
    levels = collections.Counter(words[word].level for word in words)
    print(json.dumps({
        "hsk_words": len(words), "by_level": dict(sorted(levels.items(), key=lambda item: hsk30.level_rank(item[0]))),
        "matched": report.matched, "to_write": len(updated),
        "not_in_dictionary": len(report.unmatched_headword), "reading_mismatch": len(report.unmatched_reading),
        "hsk1_not_in_dictionary": [word for word in report.unmatched_headword if words[word].level == "HSK1"],
        "examples_not_in_dictionary": report.unmatched_headword[:10],
        "examples_reading_mismatch": report.unmatched_reading[:10],
    }, ensure_ascii=False))
    if not args.apply:
        print("dry run: nothing written (use --apply --confirm-project <ref> to write)")
        return 0

    if settings is None:
        from app.platform.config import settings as configured
        settings = configured
    configured_ref = project_ref(settings.SUPABASE_URL)
    if not args.confirm_project or args.confirm_project != configured_ref:
        print(f"refused: --confirm-project must equal the configured project ref ({configured_ref or 'unset'})")
        return 2
    if settings.ENVIRONMENT == "production":
        print("refused: word-level imports are not run against ENVIRONMENT=production by this script")
        return 2
    written = 0
    for start in range(0, len(updated), args.batch_size):
        written += repository.upsert_many(updated[start:start + args.batch_size])
    print(f"done: hsk levels written on {written} entries ({configured_ref})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
