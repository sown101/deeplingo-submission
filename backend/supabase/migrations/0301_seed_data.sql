-- DeepLingo v3 migration 030: reference seed data only.

insert into v3.languages (code, name_en, name_native, script, display_order)
values
  ('en', 'English', 'English', 'Latin', 10),
  ('vi', 'Vietnamese', 'Tiếng Việt', 'Latin', 20),
  ('zh', 'Chinese', '中文', 'Han', 30),
  ('ja', 'Japanese', '日本語', 'Japanese', 40),
  ('ko', 'Korean', '한국어', 'Hangul', 50),
  ('th', 'Thai', 'ไทย', 'Thai', 60),
  ('ar', 'Arabic', 'العربية', 'Arabic', 70),
  ('hi', 'Hindi', 'हिन्दी', 'Devanagari', 80),
  ('ru', 'Russian', 'Русский', 'Cyrillic', 90)
on conflict (code) do update set
  name_en = excluded.name_en,
  name_native = excluded.name_native,
  script = excluded.script,
  display_order = excluded.display_order,
  is_active = true,
  updated_at = now();

insert into v3.romanization_systems (language_code, code, name, standard_status, notes)
values
  ('zh', 'hanyu-pinyin', 'Hanyu Pinyin', 'official', 'Standard romanization for Mandarin Chinese.'),
  ('ja', 'hepburn-romaji', 'Hepburn romanization', 'common', 'Common learner-facing Japanese romanization; generic romaji should resolve to a specific system.'),
  ('ko', 'revised-romanization', 'Revised Romanization of Korean', 'official', 'Official South Korean romanization system.'),
  ('th', 'rtgs', 'Royal Thai General System of Transcription', 'official', 'Official Thai transcription system; not always sufficient for pronunciation learning.'),
  ('ar', 'arabic-chat-transliteration', 'Arabic chat transliteration', 'informal', 'Informal Latin-script Arabic representation; not a universal standard.'),
  ('ar', 'iso-233', 'ISO 233 Arabic transliteration', 'standard', 'Scholarly transliteration standard.'),
  ('hi', 'iast', 'IAST', 'standard', 'Scholarly Indic transliteration standard.'),
  ('hi', 'itrans', 'ITRANS', 'common', 'ASCII transliteration scheme used in digital contexts.'),
  ('ru', 'iso-9', 'ISO 9', 'standard', 'One-to-one Cyrillic transliteration standard.'),
  ('ru', 'bgn-pcgn', 'BGN/PCGN Romanization', 'standard', 'Common English-language Russian romanization convention.')
on conflict (language_code, code) do update set
  name = excluded.name,
  standard_status = excluded.standard_status,
  notes = excluded.notes,
  is_active = true,
  updated_at = now();
