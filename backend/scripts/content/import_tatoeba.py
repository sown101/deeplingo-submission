"""Import a bounded Tatoeba subset as licensed example-sentence candidates.

Tatoeba text is CC BY 2.0 FR: every sentence keeps its author, and learners see the credit.
Dry run by default: parses the export files, applies the learner filters and prints counts,
writing nothing. Writing requires --apply and --confirm-project matching the configured
Supabase project reference. Re-running is idempotent (upsert on source + source_id).

    venv/Scripts/python.exe -m scripts.content.import_tatoeba --dir D:/deeplingo-corpora/tatoeba

Files expected in --dir (https://downloads.tatoeba.org/exports/per_language/):
eng_sentences_detailed.tsv.bz2, cmn_sentences_detailed.tsv.bz2, vie_sentences.tsv.bz2,
eng-vie_links.tsv.bz2, cmn-vie_links.tsv.bz2
"""
import argparse
import json
import sys
from pathlib import Path

from app.modules.content.infrastructure.corpus import tatoeba
from scripts.content.import_dictionary import project_ref


def build_rows(directory: Path, *, cap_en: int, cap_zh: int) -> list[tatoeba.CorpusRow]:
    vietnamese = tatoeba.read_all_sentences(directory / "vie_sentences.tsv.bz2")
    rows: list[tatoeba.CorpusRow] = []
    for code, language, cap in (("eng", "en", cap_en), ("cmn", "zh", cap_zh)):
        sentences = tatoeba.read_sentences(directory / f"{code}_sentences_detailed.tsv.bz2", language)
        links = tatoeba.read_links(directory / f"{code}-vie_links.tsv.bz2")
        rows += tatoeba.select_rows(sentences, language, links=links, translations=vietnamese,
                                    translation_language="vi", cap=cap)
    return rows


def main(argv: list[str] | None = None, *, repository=None, settings=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", required=True, help="folder with the Tatoeba export files")
    parser.add_argument("--max-en", type=int, default=45000, help="most English sentences to keep")
    parser.add_argument("--max-zh", type=int, default=25000, help="most Chinese sentences to keep")
    parser.add_argument("--apply", action="store_true", help="write to the configured database")
    parser.add_argument("--confirm-project", default="", help="Supabase project ref that must match configuration")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args(argv)

    rows = build_rows(Path(args.dir), cap_en=args.max_en, cap_zh=args.max_zh)
    print(json.dumps(tatoeba.summarize(rows), ensure_ascii=False))
    for language in ("en", "zh"):
        sample = next((row for row in rows if row.language_code == language), None)
        if sample:
            print(f"example {language}: {sample.text} | {sample.translations.get('vi', '-')} | {sample.author}")
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
        print("refused: corpus imports are not run against ENVIRONMENT=production by this script")
        return 2
    if repository is None:
        from app.modules.content.infrastructure.repositories.corpus_sentences import CorpusSentenceRepository
        from app.platform.supabase import supabase_service
        repository = CorpusSentenceRepository(supabase_service)
    written = 0
    for start in range(0, len(rows), args.batch_size):
        written += repository.upsert_many([row.as_record() for row in rows[start:start + args.batch_size]])
    print(f"done: {written} corpus sentences written ({configured_ref})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
