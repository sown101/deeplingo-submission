"""Synthetic bank fixtures: no curriculum import or live model drafting."""
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.content.domain.grammar_bank import GrammarBank
from scripts.content.validate_grammar_bank import main, read_bank


def draft(language="en", level="A1"):
    point = f"{language}.{level.lower()}.test_point"
    return {"format": "deeplingo-grammar-bank-v1", "catalogue_source": "deeplingo", "authorship": "ai_draft",
            "language": language, "level": level, "support_language": "vi", "version": 1,
            "topics": [{"key": "test_topic", "title": "Synthetic test topic"}],
            "points": [{"key": point, "title": "Synthetic point", "topic_key": "test_topic", "questions": [
                {"id": f"{point}.{number}", "prompt": f"Synthetic fixture {number}",
                 "options": [{"id": key, "text": text} for key, text in zip("abcd", ["alpha", "beta", "gamma", "delta"])],
                 "correct_option_id": "a", "explanation": "Synthetic fixture explanation."}
                for number in (1, 2)]}]}


def approved():
    value = draft()
    value["approval"] = {"reviewer": "owner", "approved_on": "2026-10-30",
                         "content_sha256": GrammarBank.model_validate(value).content_hash(),
                         "sample_question_ids": [value["points"][0]["questions"][0]["id"]]}
    return value


@pytest.mark.parametrize("language,level", [("en", "A1"), ("zh", "HSK1")])
def test_drafts_are_valid_but_cannot_be_released(language, level):
    bank = GrammarBank.model_validate(draft(language, level))
    assert len(bank.points[0].questions) == 2
    with pytest.raises(ValueError, match="owner sample approval"):
        bank.require_approval()


def test_approval_is_bound_to_the_whole_content_and_lists_real_samples():
    value = approved()
    bank = GrammarBank.model_validate(value)
    bank.require_approval()
    assert bank.content_hash() == value["approval"]["content_sha256"]
    for change in (lambda v: v["points"][0]["questions"][1].update(explanation="Edited explanation"),
                   lambda v: v["points"][0].update(title="Changed point"),
                   lambda v: v.update(support_language="en")):
        changed = copy.deepcopy(value)
        change(changed)
        with pytest.raises(ValidationError, match="does not match"):
            GrammarBank.model_validate(changed)
    with pytest.raises(ValidationError, match="frozen"):
        bank.points[0].questions[0].prompt = "Changed after validation"


def test_hash_is_independent_of_json_key_order_and_approval_metadata():
    value = approved()
    bank = GrammarBank.model_validate(value)
    reverse = dict(reversed(list(value.items())))
    reverse["approval"]["approved_on"] = "2026-10-29"
    assert GrammarBank.model_validate(reverse).content_hash() == bank.content_hash()


@pytest.mark.parametrize("change, expected", [
    (lambda v: v.update(language="fr"), "literal_error"),
    (lambda v: v.update(level="HSK1"), "English banks use A1 to C2"),
    (lambda v: v.update(catalogue_source="cefrj-grammar-profile-20180315"), "literal_error"),
    (lambda v: v.update(version=True), "int_type"),
    (lambda v: v.update(user_id="not-content"), "extra_forbidden"),
    (lambda v: v["points"][0].update(key="en.be_present"), "String should match pattern"),
    (lambda v: v["points"][0].update(topic_key="missing"), "every point must reference"),
    (lambda v: v["topics"].append({"key": "unused", "title": "Unused"}), "every point must reference"),
    (lambda v: v["topics"].append(copy.deepcopy(v["topics"][0])), "duplicate topic key"),
    (lambda v: v["points"].append(copy.deepcopy(v["points"][0])), "duplicate grammar point"),
    (lambda v: v["points"][0]["questions"].pop(), "at least 2"),
    (lambda v: v["points"][0]["questions"][0].update(correct_option_id="missing"), "one stored option"),
    (lambda v: v["points"][0]["questions"][0]["options"][0].update(id="b"), "duplicate option id"),
    (lambda v: v["points"][0]["questions"][0]["options"][0].update(text=" ＢＥＴＡ \n"), "duplicate option text"),
    (lambda v: v["points"][0]["questions"][0]["options"].pop(), "at least 4"),
    (lambda v: v["points"][0]["questions"][0].update(id="zh.hsk1.other.1"), "their grammar point key"),
    (lambda v: v["points"][0]["questions"][1].update(id=v["points"][0]["questions"][0]["id"]), "duplicate question id"),
    (lambda v: v["points"][0]["questions"][1].update(prompt=" SYNTHETIC   fixture 1 ",
         options=list(reversed(v["points"][0]["questions"][1]["options"]))), "duplicate question content"),
])
def test_invalid_content_is_rejected(change, expected):
    value = draft()
    change(value)
    with pytest.raises(ValidationError, match=expected):
        GrammarBank.model_validate(value)


@pytest.mark.parametrize("samples", [[], ["unknown"], ["en.a1.test_point.1", "en.a1.test_point.1"]])
def test_review_samples_must_be_nonempty_known_and_distinct(samples):
    value = approved()
    value["approval"]["sample_question_ids"] = samples
    with pytest.raises(ValidationError):
        GrammarBank.model_validate(value)


def test_cli_validates_drafts_offline_and_refuses_release(tmp_path, capsys, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("offline validation must not use the network")
    monkeypatch.setattr("socket.socket.connect", no_network)
    path = tmp_path / "bank.json"
    path.write_text(json.dumps(draft()), encoding="utf-8")
    assert main([str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["review"] == "draft"
    assert main([str(path), "--for-release"]) == 1
    assert "owner sample approval" in capsys.readouterr().out
    path.write_text(json.dumps(approved()), encoding="utf-8")
    assert main([str(path), "--for-release"]) == 0
    assert json.loads(capsys.readouterr().out)["review"] == "owner_sample_approved"


@pytest.mark.parametrize("text", ['{"format": "one", "format": "two"}', "not json"])
def test_cli_rejects_ambiguous_or_malformed_json(tmp_path, capsys, text):
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")
    assert main([str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["valid"] is False


def test_cli_reports_all_files_and_bad_input_without_echoing_content(tmp_path, capsys):
    invalid = draft()
    invalid["language"] = "INVALID_PRIVATE_INPUT"
    bad, good = tmp_path / "bad.json", tmp_path / "good.json"
    bad.write_text(json.dumps(invalid), encoding="utf-8")
    good.write_text(json.dumps(draft()), encoding="utf-8")
    assert main([str(bad), str(good), str(tmp_path / "missing.json")]) == 1
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 3 and "INVALID_PRIVATE_INPUT" not in output
    assert read_bank(good).language == "en"


@pytest.mark.parametrize("language,level,file", [("en", "A1", "en/a1.json"), ("zh", "HSK1", "zh/hsk1.json")])
def test_repository_banks_stay_within_the_owner_approved_batch(language, level, file):
    bank = read_bank(Path(__file__).resolve().parents[2] / "content/grammar_review" / file)
    assert (bank.language, bank.level, bank.support_language) == (language, level, "vi")
    # Batch approved by the owner on 2026-11-06: the first four points plus four new ones, each with a lesson.
    assert [len(point.questions) for point in bank.points] == [4, 4, 4, 4, 8, 8, 8, 8]
    assert all(point.lesson is not None for point in bank.points)
    bank.require_approval()
    assert bank.approval.reviewer == "owner"
    assert set(bank.approval.sample_question_ids) == {point.questions[0].id for point in bank.points}


def lesson():
    return {"summary": "Synthetic summary.", "rules": ["Synthetic rule."],
            "examples": [{"text": "Synthetic example one.", "meaning": "Meaning one."},
                         {"text": "Synthetic example two.", "meaning": "Meaning two."}],
            "mistakes": [{"wrong": "Wrong form", "right": "Right form", "why": "Because."}]}


def test_a_lesson_is_part_of_the_content_but_a_bank_without_one_keeps_its_hash():
    plain = GrammarBank.model_validate(draft())
    with_lesson = draft()
    with_lesson["points"][0]["lesson"] = lesson()
    taught = GrammarBank.model_validate(with_lesson)
    assert taught.content_hash() != plain.content_hash()
    assert taught.points[0].lesson.examples[0].text == "Synthetic example one."
    assert "lesson" not in json.dumps(plain.model_dump(mode="json", exclude={"approval"}, exclude_none=True))


@pytest.mark.parametrize("change", [
    lambda v: v.update(rules=[]),
    lambda v: v.update(examples=v["examples"][:1]),
    lambda v: v.update(rules=["x"] * 7),
    lambda v: v.update(mistakes=v["mistakes"] * 5),
    lambda v: v.update(summary=""),
    lambda v: v.update(extra="not allowed"),
])
def test_invalid_lessons_are_rejected(change):
    value = draft()
    value["points"][0]["lesson"] = lesson()
    change(value["points"][0]["lesson"])
    with pytest.raises(ValidationError):
        GrammarBank.model_validate(value)


@pytest.mark.parametrize("language,level", [("en", "C2"), ("zh", "HSK6")])
def test_every_level_is_accepted_for_its_own_language(language, level):
    assert GrammarBank.model_validate(draft(language, level)).level == level


@pytest.mark.parametrize("language,level", [("en", "HSK2"), ("zh", "B1")])
def test_a_level_of_the_other_language_is_rejected(language, level):
    with pytest.raises(ValidationError, match="English banks use"):
        GrammarBank.model_validate(draft(language, level))


def test_every_bank_file_in_the_repository_is_valid_and_only_approved_ones_are_served():
    from app.modules.content.infrastructure.grammar_banks import GrammarBanks
    root = Path(__file__).resolve().parents[2] / "content/grammar_review"
    files = sorted(root.glob("*/*.json"))
    assert files
    served = {(bank.language, bank.level) for language in ("en", "zh") for bank in GrammarBanks().for_language(language, "vi")}
    for path in files:
        bank = read_bank(path)
        assert path.parent.name == bank.language and path.stem == bank.level.lower(), path
        assert all(point.lesson for point in bank.points) or bank.level in ("A1", "HSK1"), path
        assert ((bank.language, bank.level) in served) == (bank.approval is not None), path
