"""Curriculum file contract, dictionary-grounded targets and the loader."""
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.content.application.curriculum_loading import (
    CurriculumFileError,
    CurriculumLoader,
    content_hash,
    parse_curriculum,
)
from app.modules.content.domain.knowledge import DictionaryEntry
from scripts.content import load_curriculum

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20261015090000_curriculum_adr019.sql"

HELLO = DictionaryEntry(
    id=uuid4(), language_code="en", headword="hello", normalized_headword="hello",
    definitions=[
        {"pos": "intj", "text": "A greeting (salutation) said when meeting someone.", "sense_id": "enwikt:hello1"},
        {"pos": "noun", "text": "\"Hello!\" or an equivalent greeting.", "sense_id": "enwikt:hello2"},
    ],
    provider_metadata={"cefr_j": "A1", "source": "en-wiktionary"},
)
NAME = DictionaryEntry(
    id=uuid4(), language_code="en", headword="name", normalized_headword="name",
    definitions=[{"pos": "noun", "text": "Any nounal word or phrase which indicates a particular person.",
                  "sense_id": "enwikt:name1"}],
    provider_metadata={"cefr_j": "A1"},
)
WENT = DictionaryEntry(
    id=uuid4(), language_code="en", headword="went", normalized_headword="went",
    definitions=[{"text": "simple past of go", "form_of": ["go"], "sense_id": "enwikt:went1"}],
)
NEGOTIATE = DictionaryEntry(
    id=uuid4(), language_code="en", headword="negotiate", normalized_headword="negotiate",
    definitions=[{"text": "To confer with others in order to reach an agreement.", "sense_id": "enwikt:neg1"}],
    provider_metadata={"cefr_j": "B2"},
)
NIHAO = DictionaryEntry(
    id=uuid4(), language_code="zh", headword="你好", normalized_headword="你好",
    definitions=[{"text": "hello; hi", "reading": "ni3 hao3", "sense_id": "cedict:nihao"}],
)

GRAMMAR = """
[[grammar]]
key = "en.be_present"
title = "Động từ to be ở hiện tại: am / is / are"
pattern = "I am … / You are … / He is …"
explanation = "Dùng am với I, is với he/she/it, are với you/we/they."
examples = [
  { text = "I am Lan.", translation = "Tôi là Lan." },
  { text = "She is a teacher.", translation = "Cô ấy là giáo viên." },
]
source = "cefrj-grammar-profile-20180315"
source_ref = "12"
"""

UNIT = """
[[units]]
key = "en.a1.u01-greetings"
title = "Chào hỏi"
topic = "Greetings and introductions"
can_do = ["Chào hỏi và nói tên mình."]
grammar = ["en.be_present"]
words = [
  { headword = "Hello", sense_id = "enwikt:hello1", gloss = "A greeting" },
  { headword = "name", sense_id = "enwikt:name1", gloss = "Any nounal word" },
]
"""


def curriculum(*, header=None, grammar=GRAMMAR, units=UNIT) -> str:
    header = header or 'format = "deeplingo-curriculum-v1"\nlanguage = "en"\nframework = "CEFR"\n' \
                       'level = "A1"\nversion = 1\ntitle = "Tiếng Anh A1"\n'
    return header + grammar + units


class FakeDictionary:
    def __init__(self, *entries):
        self.entries = {(entry.language_code, entry.normalized_headword): entry for entry in entries}

    def get_by_normalized(self, *, language_code, normalized_headword, part_of_speech=""):
        return self.entries.get((language_code, normalized_headword))


class FakeStore:
    def __init__(self, existing_hash=None):
        self.existing_hash, self.loaded = existing_hash, []

    def content_hash(self, *, language_code, framework, level):
        return self.existing_hash

    def load_level(self, payload):
        self.loaded.append(payload)
        return {"units": len(payload["units"])}


def loader(*entries, store=None):
    return CurriculumLoader(dictionary=FakeDictionary(*(entries or (HELLO, NAME))), store=store or FakeStore())


def problems(text, *entries) -> list[str]:
    with pytest.raises(CurriculumFileError) as raised:
        loader(*entries).plan(text, source_path="content/curriculum/en/a1.toml")
    return raised.value.problems


# --- File contract --------------------------------------------------------------------

def test_a_valid_file_becomes_an_ordered_dictionary_grounded_payload():
    plan = loader().plan(curriculum(), source_path="content/curriculum/en/a1.toml", grammar_inventory={"12": "A1"})
    payload = plan.payload
    assert (payload["language_code"], payload["framework"], payload["level"]) == ("en", "CEFR", "A1")
    unit = payload["units"][0]
    assert (unit["key"], unit["position"], unit["can_do"]) == ("en.a1.u01-greetings", 1, ["Chào hỏi và nói tên mình."])
    assert unit["targets"] == [
        {"position": 1, "kind": "vocabulary", "dictionary_entry_id": str(HELLO.id), "sense_id": "enwikt:hello1"},
        {"position": 2, "kind": "vocabulary", "dictionary_entry_id": str(NAME.id), "sense_id": "enwikt:name1"},
        {"position": 3, "kind": "grammar", "grammar_key": "en.be_present"},
    ]
    assert payload["grammar"][0]["examples"][0] == {"text": "I am Lan.", "translation": "Tôi là Lan."}
    assert (payload["grammar"][0]["source"], payload["grammar"][0]["source_ref"]) == (
        "cefrj-grammar-profile-20180315", "12")
    assert plan.summary["words"] == 2 and plan.summary["grammar_points"] == 1 and plan.warnings == []


@pytest.mark.parametrize("text, expected", [
    (curriculum(header='format = "v0"\nlanguage = "en"\nframework = "CEFR"\nlevel = "A1"\nversion = 1\ntitle = "x"\n'),
     "format must be"),
    (curriculum(header='format = "deeplingo-curriculum-v1"\nlanguage = "en"\nframework = "HSK"\nlevel = "HSK1"\n'
                       'version = 1\ntitle = "x"\n'), "unsupported language/framework"),
    (curriculum(header='format = "deeplingo-curriculum-v1"\nlanguage = "en"\nframework = "CEFR"\nlevel = "HSK1"\n'
                       'version = 1\ntitle = "x"\n'), "is not a CEFR level"),
    (curriculum(units=UNIT.replace("en.a1.u01", "en.a2.u01")), "must start with 'en.a1.u'"),
    (curriculum(units=UNIT.replace('grammar = ["en.be_present"]', 'grammar = ["en.unknown"]')),
     "unknown grammar point"),
    (curriculum(units=UNIT.replace('grammar = ["en.be_present"]', "grammar = []")), "not used by any unit"),
    (curriculum(units=UNIT + UNIT), "duplicate unit key"),
    (curriculum(units=UNIT.replace("enwikt:name1", "enwikt:hello1")), "duplicate sense"),
    (curriculum(units=UNIT.replace('can_do = ["Chào hỏi và nói tên mình."]', "can_do = []")), "can_do"),
    (curriculum(units=UNIT.replace('topic =', 'score = 1\ntopic =')), "Extra inputs"),
    (curriculum(grammar=GRAMMAR.replace('key = "en.be_present"', 'key = "zh.be_present"')), "must start with 'en.'"),
    ("not = [toml", "TOML"),
    (curriculum(grammar=GRAMMAR.replace("cefrj-grammar-profile-20180315", "gf0025-2021")), "source must be one of"),
    (curriculum(grammar=GRAMMAR.replace('source = "cefrj-grammar-profile-20180315"', 'source = "deeplingo"')),
     "source_ref is required for an inventory source only"),
    (curriculum(grammar=GRAMMAR.replace('source_ref = "12"\n', '')), "source_ref is required"),
])
def test_invalid_files_are_rejected_before_any_lookup(text, expected):
    assert any(expected in problem for problem in problems(text))


def test_unit_word_count_is_bounded():
    words = ",\n".join(f'{{ headword = "w{index}", sense_id = "s{index}", gloss = "g" }}' for index in range(13))
    unit = UNIT.split("words = [")[0] + f"words = [\n{words}\n]\n"
    assert any("words" in problem for problem in problems(curriculum(units=unit)))


# --- Dictionary grounding -------------------------------------------------------

def test_every_dictionary_problem_is_reported_and_nothing_is_planned():
    unit = UNIT.replace("enwikt:name1", "enwikt:gone").replace(
        '{ headword = "Hello", sense_id = "enwikt:hello1", gloss = "A greeting" }',
        '{ headword = "Hello", sense_id = "enwikt:hello1", gloss = "A farewell" },\n'
        '  { headword = "went", sense_id = "enwikt:went1", gloss = "simple past" },\n'
        '  { headword = "zzz", sense_id = "enwikt:z", gloss = "z" }')
    found = problems(curriculum(units=unit), HELLO, NAME, WENT)
    assert len(found) == 4
    assert any("gloss does not match" in problem for problem in found)
    assert any("not found (dictionary changed?)" in problem for problem in found)
    assert any("is an inflection" in problem for problem in found)
    assert any("'zzz': not in the dictionary" in problem for problem in found)


def test_grammar_points_are_checked_against_their_inventory():
    assert any("cefrj-grammar-profile-20180315 item 12 not found" in problem
               for problem in problems_with_inventory(curriculum(), {"99": "A1"}))
    above = loader().plan(curriculum(), source_path="x.toml", grammar_inventory={"12": "B1"})
    assert above.warnings == ["grammar en.be_present: cefrj-grammar-profile-20180315 item 12 is B1"]
    unchecked = loader().plan(curriculum(), source_path="x.toml")
    assert unchecked.warnings == ["grammar inventory not checked (1 point(s)); pass --grammar-inventory"]
    own = curriculum(grammar=GRAMMAR.replace('source = "cefrj-grammar-profile-20180315"\nsource_ref = "12"\n',
                                             'source = "deeplingo"\n'))
    assert loader().plan(own, source_path="x.toml").warnings == []


def problems_with_inventory(text, inventory) -> list[str]:
    with pytest.raises(CurriculumFileError) as raised:
        loader().plan(text, source_path="x.toml", grammar_inventory=inventory)
    return raised.value.problems


def test_gf0025_grammar_inventory_reads_only_item_numbers_and_levels(tmp_path):
    from app.modules.content.infrastructure.dictionaries.grammar_inventories import load_gf0025_grammar
    path = tmp_path / "hsk30-grammar.csv"
    path.write_text("No,Level,Group,Category,Details,Content\n36,1,句子的类型,特殊句型,“是”字句,（1）…\n"
                    "500,7-9,词类,副词,x,y\n", encoding="utf-8")
    assert load_gf0025_grammar(str(path)) == {"36": "HSK1", "500": "HSK7"}
    path.write_text("Word,Level\n爱,1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_gf0025_grammar(str(path))


def test_cefrj_grammar_inventory_uses_only_cefrj_levels(tmp_path):
    from app.modules.content.infrastructure.dictionaries.grammar_inventories import load_cefrj_grammar
    path = tmp_path / "cefrj-grammar-profile-20180315.csv"
    path.write_text(
        "﻿ID,Shorthand Code,Grammatical Item,Sentence Type,CEFR-J Level,FREQ*DISP,Core Inventory,EGP,GSELO,Notes\n"
        "1,PP.I_am,I am,AFF. DEC.,A1.1,A1,A1,A1,A1,\n"
        "2,PP.you_are,You are,AFF. DEC.,,A2-B1,A1,A1,A1,\n"
        "1-2,PP.am_I,Am I ...?,AFF. INT.,,,A1,A1-A2,A1,\n", encoding="utf-8")
    # Item 1-2 has levels only from Core Inventory / EGP / GSELO, which are not CEFR-J's to use.
    assert load_cefrj_grammar(str(path)) == {"1": "A1", "2": "A2", "1-2": None}
    unlevelled = loader().plan(curriculum(), source_path="x.toml", grammar_inventory={"12": None})
    assert unlevelled.warnings == ["grammar en.be_present: cefrj-grammar-profile-20180315 item 12 has no level"]


def test_a_word_above_the_level_is_a_warning_not_an_error():
    unit = UNIT.replace('{ headword = "name", sense_id = "enwikt:name1", gloss = "Any nounal word" }',
                        '{ headword = "negotiate", sense_id = "enwikt:neg1", gloss = "To confer" }')
    plan = loader(HELLO, NEGOTIATE).plan(curriculum(units=unit), source_path="x.toml", grammar_inventory={"12": "A1"})
    assert plan.warnings == ["en.a1.u01-greetings 'negotiate': dictionary level is above A1"]


def test_chinese_levels_use_hsk_and_unspaced_headwords():
    text = ('format = "deeplingo-curriculum-v1"\nlanguage = "zh"\nframework = "HSK"\nlevel = "HSK1"\n'
            'version = 1\ntitle = "Tiếng Trung HSK1"\n'
            '[[units]]\nkey = "zh.hsk1.u01-greetings"\ntitle = "Chào hỏi"\ntopic = "问候"\n'
            'can_do = ["Chào hỏi bằng tiếng Trung."]\n'
            'words = [{ headword = "你好", sense_id = "cedict:nihao", gloss = "hello" }]\n')
    plan = loader(NIHAO).plan(text, source_path="content/curriculum/zh/hsk1.toml")
    assert plan.payload["units"][0]["targets"][0]["dictionary_entry_id"] == str(NIHAO.id)


def test_the_content_hash_follows_the_content_not_the_layout():
    first = parse_curriculum(curriculum())
    reformatted = parse_curriculum(curriculum().replace('title = "Chào hỏi"', 'title   =   "Chào hỏi"'))
    changed = parse_curriculum(curriculum().replace("Chào hỏi\"", "Xin chào\""))
    assert content_hash(first) == content_hash(reformatted) != content_hash(changed)


# --- Script: dry run by default, guarded writes, unchanged skip --------------------------------

@pytest.fixture
def curriculum_file(tmp_path, monkeypatch):
    monkeypatch.setattr(load_curriculum, "BACKEND_ROOT", tmp_path)
    path = tmp_path / "content/curriculum/en/a1.toml"
    path.parent.mkdir(parents=True)
    path.write_text(curriculum(), encoding="utf-8")
    return path


def settings(environment="development"):
    return SimpleNamespace(SUPABASE_URL="https://devref.supabase.co", ENVIRONMENT=environment)


def run(args, store, **kwargs):
    return load_curriculum.main(args, dictionary=FakeDictionary(HELLO, NAME), store=store,
                                settings=kwargs.get("settings", settings()))


def test_script_dry_run_writes_nothing_and_apply_needs_the_project(curriculum_file, capsys):
    store = FakeStore()
    assert run([str(curriculum_file)], store) == 0 and store.loaded == []
    assert run([str(curriculum_file), "--apply", "--confirm-project", "wrong"], store) == 2 and store.loaded == []
    assert run([str(curriculum_file), "--apply", "--confirm-project", "devref"], store,
               settings=settings("production")) == 2 and store.loaded == []
    assert run([str(curriculum_file), "--apply", "--confirm-project", "devref"], store) == 0
    assert store.loaded[0]["source_path"] == "content/curriculum/en/a1.toml"


def test_script_skips_an_unchanged_level_and_reports_invalid_files(curriculum_file, capsys):
    plan = loader().plan(curriculum(), source_path="content/curriculum/en/a1.toml")
    store = FakeStore(existing_hash=plan.payload["content_hash"])
    assert run([str(curriculum_file), "--apply", "--confirm-project", "devref"], store) == 0
    assert store.loaded == [] and "unchanged" in capsys.readouterr().out
    curriculum_file.write_text(curriculum(units=UNIT.replace("enwikt:name1", "enwikt:gone")), encoding="utf-8")
    assert run([str(curriculum_file)], FakeStore()) == 1
    assert "invalid: 1 problem(s)" in capsys.readouterr().out


# --- Migration: global read, service-only atomic load ---------------------------------------------

def test_migration_is_public_read_and_service_only_write():
    sql = MIGRATION.read_text(encoding="utf-8")
    for table in ("curriculum_levels", "grammar_points", "curriculum_units", "curriculum_unit_targets"):
        assert f"alter table v3.{table} enable row level security" in sql
        assert f"on v3.{table} for select to anon, authenticated using (true)" in sql
    assert "returns jsonb language plpgsql security invoker\nset search_path = ''" in sql
    assert "revoke all on function v3.load_curriculum_level(jsonb) from public, anon, authenticated" in sql
    assert "grant execute on function v3.load_curriculum_level(jsonb) to service_role" in sql
    assert "provenance = 'deeplingo_authored'" in sql
    assert "(inventory_source = 'gf0025-2021' and language_code = 'zh' and inventory_ref is not null)" in sql
    assert "references v3.dictionary_entries(id) on delete restrict" in sql


def test_forms_migration_is_additive_and_keeps_the_load_contract():
    sql = (ROOT / "supabase/migrations/20261015120000_grammar_point_forms_adr019.sql").read_text(encoding="utf-8")
    assert "add column if not exists forms jsonb not null default '[]'::jsonb" in sql
    assert "jsonb_array_length(forms) <= 40" in sql and "drop " not in sql.lower()
    assert "coalesce(v_grammar->'forms', '[]'::jsonb)" in sql and "forms = excluded.forms" in sql
    assert "returns jsonb language plpgsql security invoker\nset search_path = ''" in sql
    assert "grant execute on function v3.load_curriculum_level(jsonb) to service_role" in sql


def test_grammar_forms_are_part_of_the_payload_and_must_be_distinct():
    text = curriculum(grammar=GRAMMAR.replace('pattern = "I am … / You are … / He is …"',
                                              'pattern = "I am … / You are … / He is …"\nforms = ["am", "is", "are"]'))
    plan = loader().plan(text, source_path="x.toml", grammar_inventory={"12": "A1"})
    assert plan.payload["grammar"][0]["forms"] == ["am", "is", "are"]
    duplicate = text.replace('forms = ["am", "is", "are"]', 'forms = ["am", "am"]')
    assert any("forms must be distinct" in problem for problem in problems(duplicate))
