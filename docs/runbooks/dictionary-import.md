# Nạp từ điển mở vào `v3.dictionary_entries`

Nguyên tắc: từ điển là nguồn sự thật cho nghĩa của từ, AI chỉ chọn nghĩa theo `sense_id`.

Script: `backend/scripts/content/import_dictionary.py`. Mặc định là **dry run**
(chỉ đọc file, in số lượng và mẫu, không ghi gì). Ghi vào database cần `--apply`
và `--confirm-project <project-ref>` trùng với `SUPABASE_URL` đang cấu hình; script
từ chối `ENVIRONMENT=production`. Mỗi lần ghi vào một môi trường cần được chủ dự án
cho phép trước, ghi rõ project ref.

## Nguồn dữ liệu và giấy phép

| Ngôn ngữ | Nguồn | Giấy phép | Lưu ở đâu |
| --- | --- | --- | --- |
| zh | CC-CEDICT (`cedict_ts.u8`, MDBG) | CC BY-SA 4.0 | `backend/scripts/content/data/` (đã có trong repo) |
| en | Wiktionary tiếng Anh, bản trích của kaikki.org (wiktextract) | CC BY-SA 4.0 và GFDL | **ngoài repo**, khoảng 523 MB nén |
| en | CEFR-J Wordlist 1.5 (Tono Laboratory, TUFS) | dùng thương mại được nếu ghi nguồn | ngoài repo |
| en | Octanove Vocabulary Profile C1/C2 | CC BY-SA 4.0 | ngoài repo |
| en | New General Service List 1.2 (`NGSL_12_stats.csv`) | CC BY-SA 4.0 | ngoài repo |
| en | NGSL with SFI 31K (`NGSLwithSFI-31K.xlsx`, danh sách tần suất khoảng 80.000 lemma) | CC BY-SA 4.0 | ngoài repo, đổi sang CSV |

Danh sách từ chỉ dùng để chọn tập từ cần thiết cho người học; nghĩa đều lấy từ
Wiktionary. Ghi nguồn được giữ một lần trong code (`ATTRIBUTION`, `LICENSE_URL` của
từng module trong `app/modules/content/infrastructure/dictionaries/`), mỗi dòng chỉ ghi
`provider` và `provider_metadata.source_date`. Hiển thị ghi nguồn trên client là việc
còn mở (DEBT A19).

Tải bản tiếng Anh vào một thư mục riêng ngoài repo, ví dụ `D:\deeplingo-dictionaries\en`:

```bash
curl -fL -o kaikki-en.jsonl.gz https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl.gz
curl -fL -O https://raw.githubusercontent.com/openlanguageprofiles/olp-en-cefrj/master/cefrj-vocabulary-profile-1.5.csv
curl -fL -O https://raw.githubusercontent.com/openlanguageprofiles/olp-en-cefrj/master/octanove-vocabulary-profile-c1c2-1.0.csv
curl -fL -O https://www.newgeneralservicelist.com/s/NGSL_12_stats.csv
curl -fL -O https://www.newgeneralservicelist.com/s/NGSLwithSFI-31K.xlsx
```

Đổi `NGSLwithSFI-31K.xlsx` sang `NGSLwithSFI-31K.csv` (giữ nguyên tiêu đề cột `Lemma`,
`RawFreq_Rank`), ví dụ bằng Excel/LibreOffice "Save as CSV UTF-8"; repo không thêm thư viện đọc xlsx.

## Chạy

Từ `backend/`, dry run trước:

```bash
venv/Scripts/python.exe -m scripts.content.import_dictionary --source cc-cedict --file scripts/content/data/cedict_ts.u8
```

Sau khi nhập lại CC-CEDICT, phải chạy lại phần nhập cấp HSK
([curriculum-loading.md](curriculum-loading.md#cấp-hsk-của-từ-gf-0025-2021)), vì lệnh trên ghi đè `provider_metadata`.

```bash
venv/Scripts/python.exe -m scripts.content.import_dictionary --source en-wiktionary --file D:/deeplingo-dictionaries/en/kaikki-en.jsonl.gz --word-list D:/deeplingo-dictionaries/en/cefrj-vocabulary-profile-1.5.csv --word-list D:/deeplingo-dictionaries/en/octanove-vocabulary-profile-c1c2-1.0.csv --ngsl D:/deeplingo-dictionaries/en/NGSL_12_stats.csv --frequency-list D:/deeplingo-dictionaries/en/NGSLwithSFI-31K.csv --max-rank 30000 --source-date 2026-10-03
```

Bản tiếng Anh đọc file hai lượt (lượt 1 tìm dạng biến tố, lượt 2 dựng dòng), mất
khoảng 2–3 phút. Khi số lượng và mẫu đã ổn, chạy lại cùng lệnh với
`--apply --confirm-project <project-ref>`. Upsert theo khóa
`(language_code, normalized_headword, part_of_speech)` nên chạy lại là an toàn;
`sense_id` là hash cố định của nguồn, từ, (cách đọc/từ loại) và nghĩa, nên nghĩa không
đổi thì ID không đổi.

## Tập từ tiếng Anh được giữ

- Lemma có trong CEFR-J, Octanove, NGSL, hoặc 30.000 lemma tần suất cao nhất của NGSL 31K
  (`--max-rank 30000`; cấp CEFR-J được giữ khi có).
- Dạng biến tố có mục `form_of` trỏ về một lemma đó ("went" → "go"); khi tra, resolver
  đi tiếp tới lemma và enrichment đưa ra nghĩa của lemma.
- Cụm nhiều từ (2–5 từ: cụm động từ, thành ngữ, cụm cố định, danh từ ghép) gồm lemma trên,
  dạng biến tố của chúng và từ giữ chỗ (`someone`, `one's`, …); câu cảm thán, cụm và tục ngữ
  được có một từ ngoài danh sách ("oh well"). Không lấy cụm chỉ là dạng biến tố ("gave up").
  Wiktionary chỉ nhận cụm có tính cố định, nên cụm kết hợp tự do ("sad moment") không có.
- Bỏ nghĩa `obsolete`, `archaic`, lỗi chính tả; bỏ tên riêng, tiền tố/hậu tố.
  Nếu có mục viết thường thì bỏ các mục khác kiểu chữ ("GO" không gộp vào "go").

## Dung lượng

Gói Supabase Free giới hạn 500 MB. Sau CC-CEDICT (2026-10-11): 120.666 dòng,
198.648 nghĩa, bảng 65 MB, cả database 150 MB. Sau bản tiếng Anh mở rộng (2026-10-11):
211.826 dòng, 377.510 nghĩa, 111.470 cụm nhiều từ; bảng 290 MB, database 375 MB, trong đó có
chỗ trống để lại sau hai lần nạp đè (Postgres tái sử dụng chứ không trả lại). Không chạy
`VACUUM FULL` trên gói Free khi database trên khoảng 250 MB: nó cần thêm gần bằng kích thước
bảng và có thể vượt 500 MB, làm database chuyển sang chỉ đọc. Hạn chế nạp đè toàn bộ; muốn thu
hồi dung lượng thì nâng gói hoặc làm kế hoạch riêng. Kiểm tra lại dung lượng sau mỗi lần nạp:

```sql
select pg_size_pretty(pg_total_relation_size('v3.dictionary_entries')),
       pg_size_pretty(pg_database_size(current_database()));
```

## Gỡ bỏ

Từ điển là dữ liệu tham chiếu toàn cục. Không xóa dòng đã được `concept_dictionary_links`
tham chiếu; muốn thay nguồn thì nạp đè (upsert) thay vì xóa. Xóa theo `provider` chỉ làm
khi có kế hoạch riêng được duyệt.
