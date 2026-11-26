"""The Tatoeba subset keeps short plain sentences with author and licence."""
import bz2

from app.modules.content.infrastructure.corpus import tatoeba
from scripts.content import import_tatoeba


def write(path, lines):
    with bz2.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def export(tmp_path):
    write(tmp_path / "eng_sentences_detailed.tsv.bz2", [
        "1\teng\tWe walk to school together.\talice\t2020-01-01\t2020-01-02",
        "2\teng\tWalk.\tbob\t\t",
        "3\teng\tThis sentence has 2 numbers in it.\tcarol\t\t",
        "4\teng\tI walk my dog at night.\t\\N\t\t",
        "5\teng\tWe walk to school together.\tdave\t\t",
        "6\teng\t\"Quoted\" text is not plain enough here.\teve\t\t",
        "7\teng\tShe likes to walk in the park.\tfrank\t\t",
    ])
    write(tmp_path / "cmn_sentences_detailed.tsv.bz2", [
        "10\tcmn\t我每天走路去学校。\tli\t\t",
        "11\tcmn\t我們每天走路去學校。\twang\t\t",
        "12\tcmn\tHello 你好吗？\tzhao\t\t",
        "13\tcmn\t好\tsun\t\t",
    ])
    write(tmp_path / "vie_sentences.tsv.bz2", ["100\tvie\tChúng tôi đi bộ đến trường.\tx\t\t",
                                             "101\tvie\tTôi đi bộ ở công viên.\ty\t\t"])
    write(tmp_path / "eng-vie_links.tsv.bz2", ["1\t100", "7\t101", "1\t999"])
    write(tmp_path / "cmn-vie_links.tsv.bz2", ["10\t100"])
    return tmp_path


class Repo:
    def __init__(self):
        self.batches = []

    def upsert_many(self, rows):
        self.batches.append(rows)
        return len(rows)


class Settings:
    def __init__(self, environment="development"):
        self.SUPABASE_URL = "https://abcd.supabase.co"
        self.ENVIRONMENT = environment


def test_learner_filters_keep_short_plain_sentences_only():
    assert tatoeba.is_learner_sentence("We walk to school together.", "en")
    assert not tatoeba.is_learner_sentence("Walk.", "en")
    assert not tatoeba.is_learner_sentence("We walk to school in 2020.", "en")
    assert not tatoeba.is_learner_sentence("我每天走路去学校。", "en")
    assert tatoeba.is_learner_sentence("我每天走路去学校。", "zh")
    assert not tatoeba.is_learner_sentence("我們每天走路去學校。", "zh")  # Traditional script
    assert not tatoeba.is_learner_sentence("Hello 你好吗？", "zh")


def test_rows_carry_author_licence_and_vietnamese_translation(tmp_path):
    rows = import_tatoeba.build_rows(export(tmp_path), cap_en=10, cap_zh=10)
    by_id = {(row.language_code, row.source_id): row for row in rows}
    assert set(by_id) == {("en", 1), ("en", 4), ("en", 7), ("zh", 10)}  # duplicate text and noise dropped
    first = by_id[("en", 1)].as_record()
    assert first["author"] == "alice" and first["license"] == "CC BY 2.0 FR" and first["source"] == "tatoeba"
    assert first["translations"] == {"vi": "Chúng tôi đi bộ đến trường."}
    assert by_id[("en", 4)].author is None
    assert by_id[("zh", 10)].translations == {"vi": "Chúng tôi đi bộ đến trường."}
    # Translated sentences are kept before untranslated ones when a cap applies.
    capped = import_tatoeba.build_rows(tmp_path, cap_en=2, cap_zh=1)
    assert {row.source_id for row in capped if row.language_code == "en"} == {1, 7}


def test_dry_run_writes_nothing_and_apply_needs_the_matching_project(tmp_path, capsys):
    export(tmp_path)
    repository = Repo()
    assert import_tatoeba.main(["--dir", str(tmp_path)], repository=repository, settings=Settings()) == 0
    assert repository.batches == []
    assert import_tatoeba.main(["--dir", str(tmp_path), "--apply", "--confirm-project", "other"],
                               repository=repository, settings=Settings()) == 2
    assert import_tatoeba.main(["--dir", str(tmp_path), "--apply", "--confirm-project", "abcd"],
                               repository=repository, settings=Settings("production")) == 2
    assert repository.batches == []
    assert import_tatoeba.main(["--dir", str(tmp_path), "--apply", "--confirm-project", "abcd"],
                               repository=repository, settings=Settings()) == 0
    assert sum(len(batch) for batch in repository.batches) == 4
    assert "refused" in capsys.readouterr().out
