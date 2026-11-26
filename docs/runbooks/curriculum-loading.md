# Nạp giáo trình

Giáo trình là dữ liệu tham khảo dùng chung, được viết thành file trong repo và chỉ được nạp vào
DB qua script dưới đây. Không sửa giáo trình trên dashboard.

## File

- Vị trí: `backend/content/curriculum/<ngôn ngữ>/<cấp>.toml`, ví dụ `en/a1.toml`, `zh/hsk1.toml`.
- Định dạng `deeplingo-curriculum-v1`, hợp đồng nằm ở
  `backend/app/modules/content/domain/curriculum.py`.
- Mỗi file có:
  - `format`, `language`, `framework` (`CEFR` cho `en`, `HSK` cho `zh`), `level`, `version`, `title`;
  - `[[grammar]]`: điểm ngữ pháp, gồm `key`, `title`, `pattern`, `explanation`, 2–6
    `examples`, `source` và `source_ref`:
    - `source` là danh sách gốc: `gf0025-2021` cho `zh`, `cefrj-grammar-profile-20180315`
      cho `en`, hoặc `deeplingo` khi danh sách không có điểm đó;
    - `source_ref` là số mục trong danh sách (cột `No` của `hsk30-grammar.csv`);
    - `explanation` và `examples` do DeepLingo viết;
    - `forms` (không bắt buộc): các từ cố định mà một lần dùng phải chứa, ví dụ đại từ, 是,
      am/is/are. Lượt nhận ngữ pháp chỉ giữ chỗ được chọn có chứa một trong các dạng này,
      nhờ vậy tên người không bị nhận nhầm là đại từ. Để trống với mẫu câu mở như thì hiện tại đơn;
  - `[[units]]`: theo thứ tự học. Mỗi bài có `key` (`en.a1.u01-greetings`), `title`,
    `topic`, 1–3 `can_do`, 0–2 `grammar` và 1–12 `words`.
- Mỗi từ có `headword`, `sense_id` và `gloss`:
  - `sense_id` là nghĩa trong `v3.dictionary_entries`;
  - `gloss` là phần đầu của chính nghĩa đó, để người duyệt đọc được và để script phát hiện
    nghĩa đã đổi khi nhập lại từ điển.
- Không chép giải thích, ví dụ hay thứ tự bài của sách thương mại
  (tầm nhìn sản phẩm, mục 5).

## Nạp

```bash
cd backend
venv/Scripts/python.exe -m scripts.content.load_curriculum content/curriculum/en/a1.toml
venv/Scripts/python.exe -m scripts.content.load_curriculum content/curriculum/en/a1.toml --apply --confirm-project <project-ref>
```

- **Lệnh đầu chạy thử, không ghi gì.** Nó kiểm tra file, tra mọi từ trong từ điển, rồi liệt kê
  *mọi* lỗi: từ không có trong từ điển, `sense_id` không còn, `gloss` không khớp, hoặc chọn
  nhầm nghĩa biến thể (ví dụ "went"). Từ có cấp trong từ điển cao hơn cấp của file chỉ bị cảnh báo.
- **Lệnh thứ hai mới ghi vào DB.** `--confirm-project` phải trùng project đang cấu hình, và
  script từ chối chạy với `ENVIRONMENT=production`.
- **Thay cả cấp trong một giao dịch** (`v3.load_curriculum_level`):
  - bài và điểm ngữ pháp được khớp theo `key`, nên đổi nội dung hay thứ tự vẫn giữ nguyên ID;
  - bài hoặc điểm ngữ pháp không còn trong file thì bị xoá;
  - mục tiêu của từng bài được ghi lại từ đầu.
- File không đổi (cùng `content_hash`) thì bỏ qua.

Thêm `--grammar-inventory D:/deeplingo-dictionaries/zh/hsk30-grammar.csv` (với file `zh`) để
kiểm tra từng `source_ref` có thật và đúng cấp. Thiếu tham số này thì script chỉ cảnh báo.

## Cấp HSK của từ (GF 0025-2021)

Dữ liệu nằm ngoài repo: `D:/deeplingo-dictionaries/zh/hsk30.csv` và `hsk30-grammar.csv`, lấy từ
[ivankra/hsk30](https://github.com/ivankra/hsk30) ở commit `4ff9e39`. Đây là văn bản chuẩn công
khai của Bộ Giáo dục Trung Quốc nhưng không ghi giấy phép; chỉ dùng cặp từ–cấp và số mục–cấp, và
ghi nguồn khi hiển thị cấp. Cần hỏi luật sư trước khi thương mại hóa.

```bash
cd backend
venv/Scripts/python.exe -m scripts.content.import_word_levels --file D:/deeplingo-dictionaries/zh/hsk30.csv
venv/Scripts/python.exe -m scripts.content.import_word_levels --file D:/deeplingo-dictionaries/zh/hsk30.csv --apply --confirm-project <project-ref>
```

- Một từ chỉ được gắn cấp khi khớp cả **chữ giản thể và cách đọc** với mục CC-CEDICT. Từ có
  biến thể (`哥哥|哥`) hoặc chú thích (`们（朋友们）`, `有（一）些`) được tách thành từng dạng.
- Kết quả được ghi vào `provider_metadata.hsk` (cấp thấp nhất của từ) và
  `provider_metadata.hsk_source = gf0025-2021`. Cấp 7–9 là một nhóm, ghi là `HSK7`.
- Lần chạy 2026-10-15 trên dev ghi được 10.915/10.960 từ. 34 từ không có trong CC-CEDICT
  (ở HSK1 chỉ có 车上), 11 từ lệch cách đọc; các từ này không được gắn cấp.
- **Nhập lại CC-CEDICT sẽ ghi đè `provider_metadata`**, nên phải chạy lại lệnh này sau đó.

## Sau khi nhập lại từ điển

Chạy lại lệnh chạy thử cho mọi file giáo trình. Nếu một `sense_id` biến mất, sửa file rồi nạp lại.
Mục từ điển đang được giáo trình dùng không xoá được (`on delete restrict`).
