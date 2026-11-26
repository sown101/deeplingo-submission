"""Open dictionaries loaded into `v3.dictionary_entries` and how learners must see them credited.

CC BY-SA requires attribution wherever dictionary-derived text is shown.
A provider missing from this registry is never presented as a dictionary source.
"""
from dataclasses import dataclass
from urllib.parse import quote

CC_BY_SA_4 = ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/")


@dataclass(frozen=True)
class DictionarySource:
    provider: str
    name: str
    license_name: str
    license_url: str
    home_url: str
    entry_url_template: str | None = None

    def entry_url(self, headword: str) -> str:
        if not self.entry_url_template:
            return self.home_url
        return self.entry_url_template.format(quote(headword.replace(" ", "_"), safe=""))


DICTIONARY_SOURCES: dict[str, DictionarySource] = {
    source.provider: source
    for source in (
        DictionarySource(
            provider="cc-cedict", name="CC-CEDICT", license_name=CC_BY_SA_4[0], license_url=CC_BY_SA_4[1],
            home_url="https://www.mdbg.net/chinese/dictionary?page=cc-cedict",
        ),
        DictionarySource(
            provider="en-wiktionary", name="Wiktionary", license_name=CC_BY_SA_4[0], license_url=CC_BY_SA_4[1],
            home_url="https://en.wiktionary.org/", entry_url_template="https://en.wiktionary.org/wiki/{}",
        ),
    )
}
