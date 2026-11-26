"""HSK 3.0 (GF 0025-2021) word levels recorded on CC-CEDICT entries."""
from types import SimpleNamespace

from app.modules.content.infrastructure.dictionaries import hsk30
from scripts.content import import_word_levels

CSV = (
    "ID,Simplified,Traditional,Pinyin,POS,Level,WebNo,WebPinyin,OCR,Variants,CEDICT\n"
    "L1-0001,爱,愛,ài,V,1,18,ài,爱,,愛|爱[ai4]\n"
    "L1-0100,哥哥|哥,哥哥|哥,gēge|gē,N,1,1,,,,哥哥|哥哥[ge1 ge5]/哥|哥[ge1]\n"
    "L1-0101,们（朋友们）,們,men,Suf,1,1,,,,們|们[men5]\n"
    "L1-0102,有（一）些,有（一）些,yǒu(yī)xiē,,1,1,,,,有些|有些[you3 xie1]\n"
    "L1-0213,里,裡,lǐ,N,1,1,,,,裡|里[li3]/裏|里[li3]\n"
    "L3-0500,爱,愛,ài,V,3,1,,,,愛|爱[ai4]\n"
    "L7-0001,阎王,閻王,yánwang,N,7-9,1,,,,閻王|阎王[Yan2 wang5]\n"
    "L1-0044,车上,車上,chē shang,,1,1,,,,\n"
)


def entry(headword, *readings, metadata=None):
    return {"language_code": "zh", "headword": headword, "normalized_headword": headword, "part_of_speech": "",
            "definitions": [{"text": "x", "reading": reading, "sense_id": f"cedict:{headword}{index}"}
                            for index, reading in enumerate(readings)],
            "provider_metadata": metadata or {"source": "cc-cedict"}}


def words(tmp_path):
    path = tmp_path / "hsk30.csv"
    path.write_text(CSV, encoding="utf-8")
    return hsk30.parse_word_levels(str(path)), str(path)


def test_forms_annotations_and_the_lowest_level_are_read(tmp_path):
    parsed, _ = words(tmp_path)
    assert parsed["爱"].level == "HSK1" and parsed["爱"].readings == {"ai4"}
    assert parsed["哥哥"].readings == {"ge1 ge5"} and parsed["哥"].readings == {"ge1"}
    assert "们" in parsed and "朋友们" not in parsed  # a trailing annotation is only an example
    assert {"有些", "有一些"} <= set(parsed)  # an inner annotation is an optional part
    assert parsed["阎王"].level == "HSK7" and parsed["车上"].readings == set()


def test_levels_need_a_matching_reading_and_keep_other_metadata(tmp_path):
    parsed, _ = words(tmp_path)
    rows = [entry("爱", "ai4"), entry("哥哥", "ge1 ge5"), entry("里", "li5"), entry("阎王", "Yan2 wang5"),
            entry("车上", "che1 shang5")]
    updated, report = hsk30.apply_levels(rows, parsed)
    by_word = {row["headword"]: row["provider_metadata"] for row in updated}
    assert by_word["爱"] == {"source": "cc-cedict", "hsk": "HSK1", "hsk_source": "gf0025-2021"}
    assert by_word["阎王"]["hsk"] == "HSK7"
    assert by_word["车上"]["hsk"] == "HSK1"  # no CC-CEDICT reference in the list: headword match only
    assert "里" in report.unmatched_reading and "里" not in by_word
    assert "们" in report.unmatched_headword
    already = [entry("爱", "ai4", metadata={"hsk": "HSK1", "hsk_source": "gf0025-2021"})]
    assert hsk30.apply_levels(already, parsed)[0] == []  # unchanged rows are not rewritten


class FakeRepository:
    def __init__(self, rows):
        self.rows, self.written = rows, []

    def list_rows_by_headwords(self, *, language_code, normalized_headwords):
        return [row for row in self.rows if row["normalized_headword"] in normalized_headwords]

    def upsert_many(self, rows):
        self.written += rows
        return len(rows)


def test_script_is_a_dry_run_unless_the_project_is_confirmed(tmp_path, capsys):
    _, path = words(tmp_path)
    repository = FakeRepository([entry("爱", "ai4"), entry("哥", "ge1")])
    configured = SimpleNamespace(SUPABASE_URL="https://devref.supabase.co", ENVIRONMENT="development")
    assert import_word_levels.main(["--file", path], repository=repository, settings=configured) == 0
    assert repository.written == [] and '"matched": 2' in capsys.readouterr().out
    assert import_word_levels.main(["--file", path, "--apply", "--confirm-project", "other"],
                                   repository=repository, settings=configured) == 2
    production = SimpleNamespace(SUPABASE_URL="https://devref.supabase.co", ENVIRONMENT="production")
    assert import_word_levels.main(["--file", path, "--apply", "--confirm-project", "devref"],
                                   repository=repository, settings=production) == 2
    assert repository.written == []
    assert import_word_levels.main(["--file", path, "--apply", "--confirm-project", "devref"],
                                   repository=repository, settings=configured) == 0
    assert sorted(row["headword"] for row in repository.written) == ["哥", "爱"]
