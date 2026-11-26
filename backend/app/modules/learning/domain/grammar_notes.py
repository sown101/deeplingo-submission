"""Short fixed notes for the kinds of grammar mistake the agent may name (PRD FR-8.1).

They are written text, not model output, and not yet reviewed by an editor: they exist so that the end of
a session can give a few lines about each kind of mistake without another model call. The wording says
what to watch for, never that the learner is wrong about anything or at any level.
"""
from __future__ import annotations

from collections.abc import Iterable

MAX_NOTES = 3

# code -> (note per support language, example per learning language)
_NOTES: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "verb_tense": (
        {"vi": "Chọn thì theo thời điểm: có \"yesterday\" thì dùng quá khứ (went), nói thói quen thì dùng hiện tại (goes).",
         "en": "Choose the tense by the time: \"yesterday\" asks for the past (went), a habit uses the present (goes)."},
        {"en": "Yesterday I went to the market."}),
    "subject_verb_agreement": (
        {"vi": "Chủ ngữ ngôi thứ ba số ít (he, she, it) thì động từ thêm -s: he likes, she goes.",
         "en": "With he, she or it the verb takes -s: he likes, she goes."},
        {"en": "She likes music."}),
    "articles": (
        {"vi": "Dùng a/an khi nhắc tới một danh từ đếm được lần đầu; dùng the khi cả hai người đã biết đó là cái nào.",
         "en": "Use a/an the first time you mention a countable thing; use the when both of you know which one."},
        {"en": "I saw a dog. The dog was big."}),
    "prepositions": (
        {"vi": "Giới từ đi theo cụm cố định, nên học cả cụm: in the morning, at night, on Monday.",
         "en": "Prepositions come in set phrases, so learn the whole phrase: in the morning, at night, on Monday."},
        {"en": "I go to school on Monday."}),
    "word_order": (
        {"vi": "Câu thường theo thứ tự chủ ngữ, động từ, tân ngữ; trong tiếng Trung, từ chỉ thời gian đứng trước động từ.",
         "en": "A sentence usually runs subject, verb, object; in Chinese, time words come before the verb."},
        {"en": "I eat rice every day.", "zh": "我每天吃米饭。"}),
    "plural_forms": (
        {"vi": "Danh từ đếm được số nhiều thường thêm -s: two books, three cars.",
         "en": "Countable nouns in the plural usually take -s: two books, three cars."},
        {"en": "I have two brothers."}),
    "pronouns": (
        {"vi": "Chọn đại từ theo vai trò trong câu: I hay me, he hay him, they hay them.",
         "en": "Pick the pronoun by its job in the sentence: I or me, he or him, they or them."},
        {"en": "She gave him a book.", "zh": "她给了他一本书。"}),
    "conjunctions": (
        {"vi": "Dùng liên từ đúng ý: and để thêm, but để đối lập, because để nêu lý do.",
         "en": "Use the connecting word that fits: and adds, but contrasts, because gives a reason."},
        {"en": "I was tired, but I went out.", "zh": "我很累，但是我还是出去了。"}),
    "word_choice": (
        {"vi": "Có những từ nghe gần nghĩa nhưng đi với nhau khác: make a decision, do homework.",
         "en": "Some words sound alike in meaning but pair differently: make a decision, do homework."},
        {"en": "I made a decision."}),
    "measure_words": (
        {"vi": "Tiếng Trung cần lượng từ giữa số và danh từ: 一个人, 两本书.",
         "en": "Chinese needs a measure word between the number and the noun: 一个人, 两本书."},
        {"zh": "我有两本书。"}),
    "aspect_particles": (
        {"vi": "了 nói việc đã xảy ra, 过 nói đã từng, 着 nói trạng thái đang tiếp diễn.",
         "en": "了 marks something that happened, 过 something you have done before, 着 an ongoing state."},
        {"zh": "我去过北京。"}),
    "complements": (
        {"vi": "Bổ ngữ đứng sau động từ để nói kết quả hoặc mức độ: 吃完, 说得很好.",
         "en": "A complement after the verb says the result or the degree: 吃完, 说得很好."},
        {"zh": "他说得很好。"}),
}


def grammar_notes(codes: Iterable[str], language_code: str, support_language_code: str) -> list[dict]:
    """A note for each distinct known kind of mistake (at most three), in the support language if there is
    one, else in English; with an example in the learning language when there is one."""
    language = language_code.split("-")[0].lower()
    support = support_language_code.split("-")[0].lower()
    found: list[dict] = []
    for code in dict.fromkeys(codes):
        if code not in _NOTES or len(found) >= MAX_NOTES:
            continue
        notes, examples = _NOTES[code]
        found.append({"code": code, "note": notes.get(support) or notes["en"], "example": examples.get(language)})
    return found
