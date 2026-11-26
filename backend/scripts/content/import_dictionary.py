"""Import an open dictionary into v3.dictionary_entries.

Dry run by default: parses the file and prints counts and a sample, writing nothing.
Writing requires --apply and --confirm-project matching the configured Supabase
project reference, so a wrong environment cannot be written by accident.

    venv/Scripts/python.exe -m scripts.content.import_dictionary --source cc-cedict \
        --file scripts/content/data/cedict_ts.u8
    venv/Scripts/python.exe -m scripts.content.import_dictionary --source cc-cedict \
        --file scripts/content/data/cedict_ts.u8 --apply --confirm-project <project-ref>
"""
import argparse
import json
import sys
from urllib.parse import urlparse

from app.modules.content.infrastructure.dictionaries import cc_cedict, en_wiktionary

SOURCES = {"cc-cedict", "en-wiktionary"}
SAMPLE_HEADWORDS = {"cc-cedict": "你好", "en-wiktionary": "go"}


def load_rows(source: str, path: str, *, word_lists=(), ngsl=(), frequency=(), max_rank=0,
              source_date=None) -> list[dict]:
    if source == "cc-cedict":
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
        return cc_cedict.build_rows(lines, source_date=cc_cedict.header_value(lines, "date"))
    if source == "en-wiktionary":
        if not word_lists and not ngsl and not frequency:
            raise SystemExit("en-wiktionary needs --word-list, --ngsl or --frequency-list to select learner headwords")
        if frequency and max_rank < 1:
            raise SystemExit("--frequency-list needs --max-rank")
        core = en_wiktionary.CoreWordList.from_files(cefrj=word_lists, ngsl=ngsl, frequency=frequency,
                                                     max_rank=max_rank)
        forms = en_wiktionary.collect_forms(en_wiktionary.iter_entries(path), core)
        return en_wiktionary.build_rows(en_wiktionary.iter_entries(path), core, forms, source_date=source_date)
    raise SystemExit(f"Unsupported source: {source}")


def project_ref(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host.split(".")[0] if host.endswith(".supabase.co") else host


def summarize(rows: list[dict]) -> dict:
    senses = sum(len(row["definitions"]) for row in rows)
    size = sum(len(json.dumps(row, ensure_ascii=False).encode("utf-8")) for row in rows)
    return {"rows": len(rows), "senses": senses, "approx_payload_mb": round(size / 1e6, 1)}


def main(argv: list[str] | None = None, *, repository=None, settings=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    parser.add_argument("--file", required=True)
    parser.add_argument("--apply", action="store_true", help="write to the configured database")
    parser.add_argument("--confirm-project", default="", help="Supabase project ref that must match configuration")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--word-list", action="append", default=[], help="CEFR-J style CSV (headword,pos,CEFR)")
    parser.add_argument("--ngsl", action="append", default=[], help="NGSL stats CSV (Lemma column)")
    parser.add_argument("--frequency-list", action="append", default=[],
                        help="ranked lemma CSV (NGSL 31K converted to CSV: Lemma, RawFreq_Rank)")
    parser.add_argument("--max-rank", type=int, default=0, help="keep frequency-list lemmas up to this rank")
    parser.add_argument("--source-date", default=None, help="release date of the dump, recorded per row")
    args = parser.parse_args(argv)

    rows = load_rows(args.source, args.file, word_lists=args.word_list, ngsl=args.ngsl,
                     frequency=args.frequency_list, max_rank=args.max_rank, source_date=args.source_date)
    summary = summarize(rows)
    print(json.dumps({"source": args.source, **summary}, ensure_ascii=False))
    sample = next((row for row in rows if row["headword"] == SAMPLE_HEADWORDS[args.source]), rows[0] if rows else None)
    if sample:
        print("sample:", json.dumps({k: sample[k] for k in ("headword", "pronunciation")}, ensure_ascii=False),
              json.dumps(sample["definitions"][:2], ensure_ascii=False))
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
        print("refused: dictionary imports are not run against ENVIRONMENT=production by this script")
        return 2
    if repository is None:
        from app.modules.content.infrastructure.repositories.dictionary_entries import DictionaryEntryRepository
        from app.platform.supabase import supabase_service
        repository = DictionaryEntryRepository(supabase_service)
    written = 0
    for start in range(0, len(rows), args.batch_size):
        written += repository.upsert_many(rows[start:start + args.batch_size])
        print(f"\rwritten {written}/{len(rows)}", end="", flush=True)
    print(f"\ndone: {written} rows upserted into v3.dictionary_entries ({configured_ref})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
