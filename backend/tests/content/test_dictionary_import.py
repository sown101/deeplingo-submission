"""CC-CEDICT import: parsing, stable sense IDs, resolver compatibility, safe script."""
from uuid import uuid4

from app.modules.content.application.knowledge_resolution import DictionaryEntryResolver
from app.modules.content.domain.extraction import Candidate, CandidateType
from app.modules.content.domain.knowledge import DictionaryEntry
from app.modules.content.infrastructure.dictionaries import cc_cedict
from scripts.content import import_dictionary

SAMPLE = [
    "# CC-CEDICT\n",
    "#! date=2026-03-18T08:11:41Z\n",
    "你好 你好 [ni3 hao3] /hello; hi/\n",
    "行 行 [xing2] /to walk/to go/capable/CL:個|个[ge4]/\n",
    "行 行 [hang2] /row; line/profession/\n",
    "發 发 [fa1] /to send out/to issue/\n",
    "髮 发 [fa4] /hair/\n",
    "週 周 [zhou1] /variant of 周[zhou1]/week/\n",
    "broken line without brackets\n",
]


def rows_by_headword(lines=SAMPLE):
    return {row["headword"]: row for row in cc_cedict.build_rows(lines, source_date="2026-03-18")}


def test_parse_line_splits_glosses_and_classifiers():
    entry = cc_cedict.parse_line("行 行 [xing2] /to walk/to go/capable/CL:個|个[ge4]/")
    assert entry.glosses == ("to walk", "to go", "capable")
    assert entry.classifiers == ("個|个[ge4]",)
    assert cc_cedict.parse_line("# comment") is None
    assert cc_cedict.parse_line("broken line without brackets") is None
    assert cc_cedict.parse_line("X X [x] /CL:個|个[ge4]/") is None  # no gloss left


def test_one_row_per_simplified_headword_with_every_reading_as_senses():
    rows = rows_by_headword()
    assert set(rows) == {"你好", "行", "发", "周"}
    xing = rows["行"]
    assert xing["part_of_speech"] == "" and xing["pronunciation"] == "xing2; hang2"
    assert [s["text"] for s in xing["definitions"]] == ["to walk", "to go", "capable", "row; line", "profession"]
    assert xing["definitions"][0]["classifiers"] == ["個|个[ge4]"]
    fa = rows["发"]
    assert {s["traditional"] for s in fa["definitions"]} == {"發", "髮"}
    assert [s["reading"] for s in fa["definitions"]] == ["fa1", "fa1", "fa4"]
    assert rows["周"]["definitions"][0]["is_variant_reference"] is True
    assert "is_variant_reference" not in rows["周"]["definitions"][1]
    assert rows["你好"]["provider"] == "cc-cedict"
    assert rows["你好"]["provider_metadata"] == {"source": "cc-cedict", "source_date": "2026-03-18"}


def test_sense_ids_are_stable_and_unique():
    first, second = rows_by_headword(), rows_by_headword(list(reversed(SAMPLE)))
    for headword, row in first.items():
        assert {s["sense_id"] for s in row["definitions"]} == {s["sense_id"] for s in second[headword]["definitions"]}
    ids = [s["sense_id"] for row in first.values() for s in row["definitions"]]
    assert len(ids) == len(set(ids)) and all(i.startswith("cedict:") for i in ids)


def test_header_value_reads_the_release_date():
    assert cc_cedict.header_value(SAMPLE, "date") == "2026-03-18T08:11:41Z"
    assert cc_cedict.header_value(SAMPLE, "missing") is None


class FakeEntries:
    def __init__(self, rows):
        self.rows = rows

    def get_by_normalized(self, *, language_code, normalized_headword, part_of_speech=""):
        for row in self.rows:
            if (row["language_code"], row["normalized_headword"], row["part_of_speech"]) == (
                    language_code, normalized_headword, part_of_speech):
                return DictionaryEntry(**row)
        return None

    def upsert_by_lookup(self, data):  # pragma: no cover - must not be reached when the entry exists
        raise AssertionError("imported entries must be reused, not recreated")


def test_imported_rows_are_found_by_the_existing_resolver():
    resolver = DictionaryEntryResolver(entries=FakeEntries(list(rows_by_headword().values())))
    candidate = Candidate(surface_form="行", normalized_form="行", candidate_type=CandidateType.WORD,
                          sense_gloss="to walk", sense_evidence="我们行吧", source_segment_id=uuid4(), confidence=0.9)
    entry, outcome = resolver.resolve(language_code="zh", candidate=candidate)
    assert outcome == "reused" and entry.headword == "行" and len(entry.definitions) == 5


def write_sample(tmp_path):
    path = tmp_path / "cedict_sample.u8"
    path.write_text("".join(SAMPLE), encoding="utf-8")
    return str(path)


def test_script_dry_run_writes_nothing(tmp_path, capsys):
    class Exploding:
        def upsert_many(self, rows):  # pragma: no cover
            raise AssertionError("dry run must not write")
    assert import_dictionary.main(["--source", "cc-cedict", "--file", write_sample(tmp_path)], repository=Exploding()) == 0
    assert "dry run: nothing written" in capsys.readouterr().out


class Settings:
    SUPABASE_URL = "https://devproject.supabase.co"
    ENVIRONMENT = "development"


def test_script_apply_requires_the_matching_project_ref(tmp_path, capsys):
    written = []

    class Repo:
        def upsert_many(self, rows):
            written.extend(rows)
            return len(rows)

    path = write_sample(tmp_path)
    assert import_dictionary.main(["--source", "cc-cedict", "--file", path, "--apply"],
                                  repository=Repo(), settings=Settings()) == 2
    assert import_dictionary.main(["--source", "cc-cedict", "--file", path, "--apply", "--confirm-project", "other"],
                                  repository=Repo(), settings=Settings()) == 2
    assert written == []
    assert import_dictionary.main(["--source", "cc-cedict", "--file", path, "--apply", "--confirm-project",
                                   "devproject", "--batch-size", "2"], repository=Repo(), settings=Settings()) == 0
    assert sorted(row["headword"] for row in written) == ["你好", "发", "周", "行"]


def test_script_refuses_production(tmp_path):
    class Prod(Settings):
        ENVIRONMENT = "production"

    class Repo:
        def upsert_many(self, rows):  # pragma: no cover
            raise AssertionError("must not write to production")

    assert import_dictionary.main(["--source", "cc-cedict", "--file", write_sample(tmp_path), "--apply",
                                   "--confirm-project", "devproject"], repository=Repo(), settings=Prod()) == 2
