"""English Wiktionary import: learner subset, form_of rows, sense filtering, stable IDs."""
import gzip
import json
from uuid import uuid4

from app.modules.content.application.knowledge_resolution import DictionaryEntryResolver
from app.modules.content.domain.extraction import Candidate, CandidateType
from app.modules.content.infrastructure.dictionaries import en_wiktionary as wikt
from scripts.content import import_dictionary
from tests.content.test_dictionary_import import FakeEntries


def sense(gloss, *, tags=(), parent=None, form_of=None, example=None):
    raw = {"glosses": [parent, gloss] if parent else [gloss], "tags": list(tags)}
    if form_of:
        raw["form_of"] = [{"word": form_of}]
    if example:
        raw["examples"] = [{"text": example}]
    return raw


ENTRIES = [
    {"word": "go", "pos": "verb", "lang_code": "en",
     "sounds": [{"ipa": "/ɡəʊ/", "tags": ["Received-Pronunciation"]}, {"ipa": "/ɡoʊ/", "tags": ["General-American"]}],
     "senses": [sense("To move through space.", parent="To move:", example="Why don't you go with us?"),
                sense("To walk; to proceed.", tags=["obsolete"])]},
    {"word": "go", "pos": "noun", "lang_code": "en", "senses": [sense("An attempt, a try.")]},
    {"word": "Go", "pos": "name", "lang_code": "en", "senses": [sense("A surname.")]},
    {"word": "went", "pos": "verb", "lang_code": "en",
     "senses": [sense("simple past of go", tags=["form-of", "past"], form_of="go")]},
    {"word": "wend", "pos": "verb", "lang_code": "en", "senses": [sense("To travel.")]},
    {"word": "give up", "pos": "verb", "lang_code": "en", "senses": [sense("To stop trying.")]},
    {"word": "break the ice", "pos": "verb", "lang_code": "en", "senses": [sense("To start a conversation.")]},
    {"word": "zymurgy lab", "pos": "noun", "lang_code": "en", "senses": [sense("A lab.")]},
    {"word": "Ice", "pos": "noun", "lang_code": "en", "senses": [sense("Methamphetamine.", tags=["slang"])]},
    {"word": "ice", "pos": "noun", "lang_code": "en", "senses": [sense("Frozen water.")]},
    {"word": "go", "pos": "verb", "lang_code": "fr", "senses": [sense("Not English.")]},
]

CORE = wikt.CoreWordList()
for word, level in [("go", "A1"), ("give", "A1"), ("up", "A1"), ("break", "A2"), ("ice", "A2"), ("lab", None)]:
    CORE.add(word, level)


def rows():
    english = [entry for entry in ENTRIES if entry["lang_code"] == "en" and entry["pos"] != "name"]
    forms = wikt.collect_forms(english, CORE)
    return {row["normalized_headword"]: row for row in wikt.build_rows(english, CORE, forms, source_date="2026-10-03")}


def test_learner_subset_keeps_core_forms_and_known_expressions():
    assert wikt.collect_forms(ENTRIES[:5], CORE) == {"went"}
    assert set(rows()) == {"go", "went", "give up", "break the ice", "ice"}


def test_rows_merge_parts_of_speech_and_drop_obsolete_senses():
    go = rows()["go"]
    assert go["part_of_speech"] == "" and go["language_code"] == "en"
    assert [(s["pos"], s["text"]) for s in go["definitions"]] == [("verb", "To move through space."),
                                                                 ("noun", "An attempt, a try.")]
    assert go["definitions"][0]["parent"] == "To move:"
    assert go["definitions"][0]["example"] == "Why don't you go with us?"
    assert go["pronunciation"] == "US /ɡoʊ/; UK /ɡəʊ/"
    assert go["provider_metadata"] == {"source": "en-wiktionary", "source_date": "2026-10-03", "cefr_j": "A1"}


def test_inflection_rows_point_to_their_lemma():
    went = rows()["went"]["definitions"][0]
    assert went["form_of"] == ["go"] and went["tags"] == ["past"]


def test_lower_case_entry_wins_over_differently_cased_entries():
    ice = rows()["ice"]
    assert ice["headword"] == "ice" and [s["text"] for s in ice["definitions"]] == ["Frozen water."]
    only_capitalized = [{"word": "Ice", "pos": "noun", "lang_code": "en", "senses": [sense("Methamphetamine.")]}]
    [row] = wikt.build_rows(only_capitalized, CORE, set())
    assert row["headword"] == "Ice" and row["normalized_headword"] == "ice"


def test_inflected_expressions_and_unknown_words_are_skipped():
    gave_up = {"word": "gave up", "pos": "verb", "lang_code": "en",
               "senses": [sense("simple past of give up", tags=["form-of"], form_of="give up")]}
    assert not wikt.is_relevant(gave_up, CORE, {"went"})
    unknown = {"word": "zymurgy lab", "pos": "noun", "lang_code": "en", "senses": [sense("A lab.")]}
    assert not wikt.is_relevant(unknown, CORE, set())


def test_expressions_may_contain_inflected_forms_and_phrases_one_unlisted_word():
    def entry(word, pos):
        return {"word": word, "pos": pos, "lang_code": "en", "senses": [sense("Meaning.")]}

    core = wikt.CoreWordList(levels={**CORE.levels, "get": "A1", "start": "A1"})
    assert wikt.is_relevant(entry("get started", "verb"), core, {"started"})
    assert wikt.is_relevant(entry("oh go", "intj"), CORE, set())  # "oh" is not listed
    assert not wikt.is_relevant(entry("oh go", "noun"), CORE, set())
    assert not wikt.is_relevant(entry("oh zymurgy go", "phrase"), CORE, set())


def test_sense_ids_are_stable_and_unique():
    first, second = rows(), rows()
    assert first == second
    ids = [s["sense_id"] for row in first.values() for s in row["definitions"]]
    assert len(ids) == len(set(ids)) and all(i.startswith("enwikt:") for i in ids)


def test_core_word_list_keeps_the_lowest_cefr_level_and_splits_variants():
    words = wikt.CoreWordList()
    words.add("colour/color", "B1")
    words.add("color", "A2")
    words.add("color", None)
    assert words.levels == {"colour": "B1", "color": "A2"}


def test_frequency_list_adds_ranked_lowercase_lemmas_up_to_the_cut(tmp_path):
    path = tmp_path / "ngsl31k.csv"
    path.write_text("Lemma,Wordlist,RawFreq_Rank\nthe,1 - NGSL,1\nintriguing,,9000\nMonday,,500\n"
                    "e-mail,,700\nunsinkable,,29810\nbrainer,,30002\nbroken,,\n", encoding="utf-8")
    words = wikt.CoreWordList()
    words.add("intriguing", "B2")
    words.add_frequency_list(str(path), max_rank=30000)
    assert set(words.levels) == {"the", "intriguing", "unsinkable"}
    assert words.levels["intriguing"] == "B2"  # a CEFR level is never erased by the frequency list


def test_imported_rows_are_found_by_the_existing_resolver():
    resolver = DictionaryEntryResolver(entries=FakeEntries(list(rows().values())))
    candidate = Candidate(surface_form="give up", normalized_form="give up", candidate_type=CandidateType.PHRASE,
                          sense_gloss="stop trying", sense_evidence="Never give up.", source_segment_id=uuid4(),
                          confidence=0.9)
    entry, outcome = resolver.resolve(language_code="en", candidate=candidate)
    assert outcome == "reused" and entry.definitions[0]["text"] == "To stop trying."


def test_resolver_follows_inflection_rows_to_their_lemma_and_falls_back_to_surface():
    resolver = DictionaryEntryResolver(entries=FakeEntries(list(rows().values())))

    def resolve(surface, normalized):
        candidate = Candidate(surface_form=surface, normalized_form=normalized, candidate_type=CandidateType.WORD,
                              sense_gloss="move", sense_evidence=surface, source_segment_id=uuid4(), confidence=0.9)
        entry, outcome = resolver.resolve(language_code="en", candidate=candidate)
        return (entry.headword if entry else None), outcome

    assert resolve("went", "went") == ("go", "reused_lemma")
    assert resolve("Ice", "ice cube") == ("ice", "reused")  # normalized form missing, surface found
    assert resolve("wend", "wend") == (None, "missing_authoritative_source")


def test_script_dry_run_reads_gzip_dump_and_word_lists(tmp_path, capsys):
    dump = tmp_path / "kaikki.jsonl.gz"
    with gzip.open(dump, "wt", encoding="utf-8") as handle:
        for entry in ENTRIES:
            handle.write(json.dumps(entry) + "\n")
    cefrj = tmp_path / "cefrj.csv"
    cefrj.write_text("headword,pos,CEFR\ngo,verb,A1\nice,noun,A2\n", encoding="utf-8")
    ngsl = tmp_path / "ngsl.csv"
    ngsl.write_text("Lemma,SFI Rank\ngive,1\nup,2\n", encoding="utf-8")

    class Exploding:
        def upsert_many(self, rows):  # pragma: no cover
            raise AssertionError("dry run must not write")

    assert import_dictionary.main(["--source", "en-wiktionary", "--file", str(dump), "--word-list", str(cefrj),
                                   "--ngsl", str(ngsl)], repository=Exploding()) == 0
    out = capsys.readouterr().out
    assert '"rows": 4' in out and "dry run: nothing written" in out


def test_script_requires_a_word_list_for_english(tmp_path):
    try:
        import_dictionary.main(["--source", "en-wiktionary", "--file", str(tmp_path / "missing.jsonl")])
    except SystemExit as exit_:
        assert "word-list" in str(exit_)
    else:  # pragma: no cover
        raise AssertionError("expected SystemExit")
