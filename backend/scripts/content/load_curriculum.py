"""Validate a curriculum file and load it into v3.

Dry run by default: validates the file against the dictionary and prints a summary and any
warnings, writing nothing. Writing requires --apply and --confirm-project matching the
configured Supabase project reference.

    venv/Scripts/python.exe -m scripts.content.load_curriculum content/curriculum/en/a1.toml
    venv/Scripts/python.exe -m scripts.content.load_curriculum content/curriculum/en/a1.toml \
        --apply --confirm-project <project-ref>
"""
import argparse
import json
import sys
from pathlib import Path

from app.modules.content.application.curriculum_loading import CurriculumFileError, CurriculumLoader
from scripts.content.import_dictionary import project_ref

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None, *, dictionary=None, store=None, settings=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file")
    parser.add_argument("--apply", action="store_true", help="write to the configured database")
    parser.add_argument("--confirm-project", default="", help="Supabase project ref that must match configuration")
    parser.add_argument("--grammar-inventory", default=None,
                        help="inventory CSV for the file's language (zh: hsk30-grammar.csv, "
                             "en: cefrj-grammar-profile-20180315.csv)")
    args = parser.parse_args(argv)

    path = Path(args.file).resolve()
    try:
        source_path = path.relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        print("refused: curriculum files must live inside the backend repository")
        return 2
    if dictionary is None or store is None:
        from app.modules.content.infrastructure.repositories.curriculum import CurriculumRepository
        from app.modules.content.infrastructure.repositories.dictionary_entries import DictionaryEntryRepository
        from app.platform.supabase import supabase_service
        dictionary = dictionary or DictionaryEntryRepository(supabase_service)
        store = store or CurriculumRepository(supabase_service)
    loader = CurriculumLoader(dictionary=dictionary, store=store)
    try:
        inventory = load_inventory(args.grammar_inventory, path) if args.grammar_inventory else None
        plan = loader.plan(path.read_text(encoding="utf-8"), source_path=source_path, grammar_inventory=inventory)
    except CurriculumFileError as exc:
        print(f"invalid: {len(exc.problems)} problem(s)")
        for problem in exc.problems:
            print(f"  - {problem}")
        return 1
    print(json.dumps(plan.summary, ensure_ascii=False))
    for warning in plan.warnings:
        print(f"  warning: {warning}")
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
        print("refused: curriculum loads are not run against ENVIRONMENT=production by this script")
        return 2
    if loader.is_unchanged(plan):
        print("unchanged: the loaded level already has this content hash")
        return 0
    print(json.dumps({"loaded": loader.apply(plan), "project": configured_ref}, ensure_ascii=False))
    return 0


def load_inventory(inventory_path: str, curriculum_path: Path) -> dict[str, str]:
    from app.modules.content.application.curriculum_loading import parse_curriculum
    from app.modules.content.infrastructure.dictionaries import grammar_inventories
    language = parse_curriculum(curriculum_path.read_text(encoding="utf-8")).language
    if language == "zh":
        return grammar_inventories.load_gf0025_grammar(inventory_path)
    if language == "en":
        return grammar_inventories.load_cefrj_grammar(inventory_path)
    raise CurriculumFileError([f"no grammar inventory reader for language {language!r} yet"])


if __name__ == "__main__":
    sys.exit(main())
