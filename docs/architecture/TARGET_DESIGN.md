# Thiết kế đích sau tái cấu trúc (2026-11-14)

Chủ dự án duyệt hướng này ngày 2026-11-14; quyết định sản phẩm nằm ở PRD mục 8.10. Tài liệu này là
thiết kế kỹ thuật cho cả năm giai đoạn. Ranh giới module hiện tại vẫn ở `BACKEND_BOUNDARIES.md`;
mỗi giai đoạn xong thì sửa tài liệu đó cho khớp code và gạch phần tương ứng ở đây.

**Cập nhật 2026-11-15 (đợt thu gọn).** App Flutter đã bỏ khỏi kho (tag `archive/flutter-app-20261115`), nên không
còn lớp chuyển tiếp nào. Engine phiên học cũ, module `assessment`, các endpoint chuyển tiếp và tính năng "bỏ qua từ"
đã xóa khỏi code; bảng và hàm SQL của chúng có file migration nháp `20261116090000`–`20261116094000`, chưa áp.

## 1. Nguyên tắc

1. **Một nguồn sự thật cho mỗi việc.** Mọi việc người học làm ghi vào *nhật ký học tập*; Tiến bộ,
   Home và agent đều đọc từ đó. Không màn hình nào giữ kết quả riêng.
2. **Một engine cho mỗi loại logic.** Một engine ôn FSRS, một engine bài tập, một lõi agent.
   Các màn hình chỉ là cách hiển thị.
3. **Theo ngôn ngữ.** Mọi dữ liệu của người học có `language_code` tham chiếu bảng `languages`;
   không khóa cứng `en`/`zh` trong code hay ràng buộc DB.
4. **Agent là trung tâm.** Agent đọc được mọi thứ người học làm qua tool có giới hạn và giao việc
   qua *yêu cầu học*. Không có dữ liệu nào chỉ màn hình thấy mà agent không thấy.
5. **Ít thủ tục.** `Protocol` chỉ ở biên ra ngoài (LLM, giọng nói, Azure, Supabase); repository nội
   bộ dùng class cụ thể và một bộ fake dùng chung cho test. File mới tối đa khoảng 400 dòng.
6. **Một client: web.** Endpoint mới thay endpoint cũ; không giữ lớp chuyển tiếp (app Flutter đã bỏ 2026-11-15).
7. **Test kiểm hành vi, không kiểm chữ trong mã nguồn.** Không thêm test đọc file nguồn hay hash
   migration; test cũ kiểu đó bị xóa khi đụng tới phần liên quan.

## 2. Bức tranh tổng thể

```
               ┌──────────── Web (React) ───────────────────────────┐
               │ Home · Video & vùng học · Sổ tay · Tata · Tiến bộ   │
               └───────────────┬───────────────────────┬─────────────┘
                     REST (/learner/me/...)      WebSocket (voice)
┌──────────────────────────────┴───────────────────────┴──────────────────┐
│ content      video, transcript (AI), dịch câu, từ điển, ngữ pháp bank   │
│ notebook     từ, cụm từ, điểm ngữ pháp đã lưu; sổ tay; bộ từ có sẵn      │
│ practice     engine bài tập: sinh câu hỏi, chấm, ghi nhật ký             │
│ review       FSRS theo ngôn ngữ (bộ thẻ kiểu Anki)                       │
│ activity     nhật ký học tập + yêu cầu học + chuỗi ngày                  │
│ agent        lõi agent, tool, ngữ cảnh, kênh giọng nói/chữ, eval         │
│ progress     số liệu đọc từ activity + review                            │
│ identity/learner  đăng nhập, hồ sơ, ngôn ngữ, đồng ý, xuất/xóa dữ liệu   │
└────────────────────────── Supabase Postgres (schema v3) ────────────────┘
```

Luồng ghi chung của mọi bài tập:
`client gửi câu trả lời → practice chấm → (nếu là mục từ vựng) review cập nhật FSRS
→ activity ghi một dòng nhật ký (idempotent theo client_event_id) → trả kết quả`.

## 3. Mô hình dữ liệu đích

### Bảng mới

**`learner_activity_log`** (chỉ ghi thêm; giữ lâu dài; người học xem, xuất, xóa được)

| Cột | Ý nghĩa |
|---|---|
| `id`, `user_id`, `language_code` | khóa; ngôn ngữ tham chiếu `languages` |
| `client_event_id` | chống ghi trùng khi gửi lại (unique theo user) |
| `kind` | `video_watched`, `lookup`, `word_saved`, `dictation`, `shadowing`, `region_question`, `flashcard`, `choice`, `cloze`, `listening`, `pronunciation`, `writing`, `grammar_lesson`, `grammar_exercise`, `speaking_turn`, `speaking_session`, `roleplay` |
| `item_type`, `item_id` | `concept` / `grammar_point` / `segment` / `region`; có thể rỗng |
| `source_type`, `source_id` | `video_region`, `notebook`, `review_deck`, `agent_session` |
| `outcome` | `correct` / `incorrect` / `partial` / `done` |
| `score` | 0–100 khi có (điểm Azure, tỉ lệ đúng dictation) |
| `detail` | jsonb nhỏ, có giới hạn kích thước (không chứa âm thanh) |
| `occurred_at` | thời điểm |

**`learner_study_requests`** (việc agent hoặc hệ thống giao)

| Cột | Ý nghĩa |
|---|---|
| `id`, `user_id`, `language_code` | |
| `kind` | `grammar_redo`, `word_review`, `pronunciation_retry`, `region_practice` |
| `item_type`, `item_id`, `reason` | ví dụ điểm ngữ pháp và câu sai (đã cắt ngắn) |
| `status` | `open` / `done` / `dismissed`; tự chuyển `done` khi nhật ký có kết quả đúng của mục đó |
| `created_by` | `agent` / `system`; `created_at`, `closed_at` |

**`learner_grammar_progress`** (thay `learner_grammar_review_results`): mỗi điểm ngữ pháp: đã học bài
chưa, số bài làm, lần đúng gần nhất. Không FSRS.

### Bảng đổi
- `user_language_preferences`: mỗi ngôn ngữ đang học là một dòng; `review_states` thêm `language_code`
  để chia bộ thẻ theo ngôn ngữ (lấy từ concept).
- Mọi ràng buộc `language_code in ('en','zh')` đổi thành khóa ngoại tới `languages`. Hiện có 1 ràng
  buộc DB (`speaking_sessions`) và 6 chỗ trong code (`lexical_profile`, `grammar_bank`, `api/realtime`,
  `session_events`, `speaking_history`, `config`). Chỗ phụ thuộc năng lực thật (chép lời AI đã kiểm
  cho ngôn ngữ nào) chuyển thành cột năng lực trong `languages`.

### Bảng bỏ (sau khi dữ liệu đã chuyển)
- `learner_practice_events` (90 ngày) → nhật ký.
- `learner_grammar_review_results` → `learner_grammar_progress` + nhật ký.
- `speaking_sessions` (hết hạn 15 phút, chỉ để xử lý) → giữ làm hàng đợi xử lý nội bộ hoặc thay
  bằng bảng công việc của agent; kết quả cuối ghi nhật ký.
- `learning_sessions`, `session_activities`, `attempts` của Quick review cũ → engine bài tập mới
  không cần phiên lưu trên server. Code đã xóa 2026-11-15; bảng bỏ bằng migration nháp `20261116091000`
  (cùng `learner_grammar_review_results`), `learner_quick_review_skips` bằng `20261116094000`.

Cuối GĐ5: gộp toàn bộ migration thành một baseline, sau khi so khớp với schema thật trên dev.

## 4. Giai đoạn 1 — Nhật ký học tập và yêu cầu học

**Mục tiêu.** Mọi bài tập hiện có đều có kết quả lâu dài ở một chỗ; agent đọc được.

**Backend.** Module `activity` gồm: repository nhật ký (ghi idempotent, đọc theo ngôn ngữ/khoảng
thời gian/loại, có trần số dòng), repository yêu cầu học, service `record(...)` dùng chung.
Gắn `record` vào: dictation, shadowing, câu hỏi vùng học, tra từ, lưu từ, Quick review (chọn,
điền), flashcard (`memory-rating`), phát âm từ điển, ôn ngữ pháp, kết thúc phiên nói.
Endpoint: `GET /learner/me/activity?language=&since=&kinds=` và
`GET|POST /learner/me/study-requests`, `POST .../{id}/dismiss`.
Tool agent: `get_recent_activity`, `get_study_requests`, `create_study_request`.
Xuất dữ liệu và xóa tài khoản bao gồm hai bảng mới.

**DB.** Migration tạo hai bảng, RLS chỉ service-role (như các bảng khác), bỏ hạn 90 ngày của
`learner_practice_events` (giữ đến khi bảng bị bỏ). Áp lên dev cần chủ dự án duyệt.

**Web/App.** Không đổi màn hình (chỉ ghi thêm). Thông báo quyền riêng tư sửa câu "90 ngày".

**Xóa trong GĐ1.** Hàm dọn dữ liệu hết hạn của nhật ký luyện; test kiểm hạn 90 ngày.

**Xong khi.** Mỗi luồng: làm bài một lần → đúng một dòng nhật ký; gửi lại → không thêm dòng;
người khác không đọc được; tool agent trả đúng ngôn ngữ và có trần. Toàn bộ test xanh.

## 5. Giai đoạn 2 — Sổ tay và một engine ôn tập

**Trạng thái (2026-11-14): code written, tested locally; migration đã áp lên dev.** Đã làm: module `practice`
(sinh/chấm sáu loại bài, bộ thẻ theo ngôn ngữ, `v3.submit_review_answer`, ngữ pháp với `learner_grammar_progress`
và "Cần làm lại"), quy đổi điểm một chỗ (`review/domain/grades.py`), các màn web mới, xóa các màn web liệt kê
dưới đây. **Đã xóa 2026-11-15:** backend `quick_review`, `execution`, `generation`, `activity_builders`, `activity_checks`,
`video_learning` (known-check) và module `assessment`. **Còn lại:** áp các migration nháp bỏ hàm SQL phiên và bảng
`learning_sessions`, `session_activities`, `attempts` (sau khi backend mới được deploy).

**Mục tiêu.** Thay bốn đường ôn (Quick review, notebook study, grammar review, known-check) bằng
một engine; sổ tay có hai phần Từ vựng và Ngữ pháp.

**Từ vựng.**
- *Bộ thẻ theo ngôn ngữ* như Anki: mỗi ngôn ngữ một hàng đợi FSRS; Home và Sổ tay hiện số thẻ đến
  hạn của từng ngôn ngữ.
- *Engine bài tập* (`practice`): một hàm sinh câu hỏi theo `exercise_type` và một hàm chấm. Loại:
  `flashcard`, `choice` (chọn nghĩa), `listening` (nghe chọn từ), `cloze` (điền vào câu, ưu tiên
  câu từ video gốc), `pronunciation` (Azure), `writing`.
- *Tập viết cho mọi ngôn ngữ*: chữ Hán/Kanji dùng hanzi-writer theo thứ tự nét; chữ Latin và
  chữ khác là viết lại từ khi nghe (chấm theo chuẩn hóa dấu tùy chọn).
- *Quy đổi điểm FSRS một chỗ*: flashcard theo người học tự chấm; bài có chấm: sai → Again,
  đúng có gợi ý → Hard, đúng → Good, đúng nhanh liên tiếp → Easy. Mỗi thẻ đổi lịch tối đa một
  lần mỗi lượt ôn.
- Phiên ôn chạy phía client trên danh sách thẻ server trả (`GET /learner/me/review/{language}/due`),
  mỗi câu trả lời gửi `POST /learner/me/review/answers` (chấm + FSRS + nhật ký trong một giao dịch).

**Ngữ pháp (không FSRS).** Bài học (nội dung bank đã duyệt) → bài tập (trắc nghiệm, điền, biến đổi
câu) → kết quả vào `learner_grammar_progress` và nhật ký. Mục "Cần làm lại" lấy từ yêu cầu học
`grammar_redo` của agent; làm đúng thì yêu cầu tự đóng.

**Web.** Sổ tay: kệ theo ngôn ngữ → bộ thẻ đến hạn; trong sổ: danh sách từ, chọn cách luyện;
tab Ngữ pháp: bài học, bài tập, "Cần làm lại". Một màn phiên ôn dùng chung cho mọi loại bài.

**Xóa trong GĐ2.** Web: `QuickReviewScreen`, `LearningSessionScreen`, `FamiliarizationCards`,
`useSessionRunner`, `learningSessionReducer`, các màn riêng `FlashcardScreen`/`PracticeScreen`/
`WritingScreen` (thay bằng màn phiên ôn chung), `GrammarReview` cũ. Backend: `quick_review`,
`execution`, `generation`, `activity_builders`, `activity_checks`, `example_practice`,
`video_learning` (known-check), `assessment` (gộp vào `practice`), hàm SQL
`start_or_resume_quick_review_session` và các hàm phiên. Endpoint cũ đã xóa 2026-11-15.

**Xong khi.** Mỗi loại bài: sinh câu, chấm, FSRS đổi đúng một lần, nhật ký đúng một dòng; bộ thẻ
không lẫn ngôn ngữ; yêu cầu `grammar_redo` đóng khi làm đúng. E2E: một phiên ôn từ đầu đến cuối
cho `en` và `zh`.

## 6. Giai đoạn 3 — Video và vùng học (XONG 2026-11-14, nhánh `feat/video-region`)

**Luồng.** Import YouTube → transcript (AI qua Gemini, vì VM bị chặn yt-dlp; giữ phương án phụ đề
YouTube khi chạy được) → dịch từng câu sang ngôn ngữ người học chọn → xem với phụ đề song ngữ →
bôi đen từ hoặc cụm từ để tra; bấm câu để giải thích ngữ pháp → lưu vào sổ tay.

**Phụ đề song ngữ.** Bảng `segment_translations` đã có; dịch theo `support_language` khi người học
mở video lần đầu, lưu dùng chung cho mọi người học cùng ngôn ngữ. Hiển thị: câu gốc trên, nghĩa
dưới; bật/tắt nghĩa; câu đang phát được làm nổi.

**Vùng học là đơn vị luyện.** Chọn một đoạn → khung "Luyện vùng" có ba tab Dictation, Shadowing,
Câu hỏi → mỗi lần làm ghi nhật ký với `source=video_region` → hết vùng hiện thẻ kết quả (đúng/sai
dictation, điểm shadowing trung bình, câu hỏi đúng, từ mới đã lưu) → nút "Nói về đoạn này với Tata"
mở agent ở chế độ vùng học.

**Web.** Tách `WatchScreen` (853 dòng) thành: trình phát + transcript, khung tra từ/ngữ pháp,
khung Luyện vùng, thẻ kết quả.

**Xóa trong GĐ3.** Ghi `learner_practice_events` (đã chuyển sang nhật ký), endpoint
`practice-events/*`, `session-summary` cũ (thay bằng thẻ kết quả vùng).
*Đã làm:* web không còn gọi `session-summary` (thẻ kết quả vùng thay); `SessionSummaryCard` và bộ giải mã tóm tắt phiên trên web đã xóa cùng test của chúng. *Còn lại:* endpoint `practice-events/*`, `session-summary` và việc ghi `learner_practice_events` vẫn còn trong backend (GĐ4 đã chuyển agent sang đọc nhật ký); chưa xóa trong đợt 2026-11-15. Mã vùng = `<id câu đầu>_<id câu cuối>` (`app/kernel/region_ids.py`), không cần bảng hay migration.

**Xong khi.** Phụ đề song ngữ đúng ngôn ngữ chọn; tra cụm từ bằng bôi đen; mỗi bài trong vùng có
kết quả lưu và hiện trên thẻ kết quả; E2E một vùng học trọn vẹn.

## 7. Giai đoạn 4 — Agent (XONG 2026-11-14, nhánh `feat/agent-core`)

**Trạng thái: code written, tested locally; không có migration; chưa deploy.** Đã làm: gói
`learning/application/agent/` gồm `session.py` (`AgentSession`: chào → luyện → tổng kết → kết thúc, chế độ
`region`/`topic`/`roleplay`), `context.py` (`ContextBuilder`: hồ sơ, 20 dòng nhật ký gần nhất, vùng học, thẻ đến hạn
theo ngôn ngữ, yêu cầu học đang mở; cache 60 giây), `tools.py` (`ToolRegistry`: 7 tool đọc, 6 tool hiển thị, 6 tool
hành động; schema một chỗ, Gemini dùng bản chuyển đổi), `scaffolding.py` (đồng hồ giả được trong test), `prompts.py`
(mọi prompt và cue, kể cả `HELP_CUES`), `setup.py` (ngữ cảnh cuộc nói), hai kênh `voice.py` (Gemini Live) và `text.py`
(theo lượt, nhận cả chữ gõ), `evals.py` (7 kịch bản). Port `AgentFacts` nối trong `bootstrap/wiring/agent.py`.
Agent đọc việc gần đây từ nhật ký (không còn đọc `learner_practice_events`). Cờ `COMPANION_PROFILE_BRIEF`, `COMPANION_GRAMMAR_LESSONS`, `COMPANION_SESSION_EVENTS_ENABLED`,
`COMPANION_AGENT_TOOLS`, `COMPANION_REALTIME_ENABLED` đã bỏ; kênh cấu hình bằng `AGENT_CHANNELS` (`text`, `voice`).
Web: một màn Agent, dự phòng chữ/ghi âm nằm trong màn giọng nói, đã xóa `CompanionScreen`. Eval thật chạy bằng
`scripts/agent/eval_live.py`. **Còn lại:** gợi mở 5 giây chỉ có ở kênh giọng nói (kênh chữ không đo được im lặng
trên server, chỉ nhận từ đệm/"không biết nói").

### Vai trò và chế độ
1. **Đồng hành giao tiếp**: (a) *vùng học*: giảng ngữ pháp, cách dùng, nội dung của đoạn video;
   (b) *chủ đề*: thảo luận một chủ đề người học chọn hoặc agent đề xuất từ sở thích.
2. **Đóng vai** trong tình huống (kịch bản có mục tiêu giao tiếp và từ trọng tâm).

### Kiến trúc
Theo các nguyên tắc chung mà Anthropic ("Building effective agents"), OpenAI (Agents SDK) và Google
cùng khuyến nghị: một vòng lặp đơn giản, tool rõ ràng, ngữ cảnh được lắp có chủ đích, guardrail
và eval. Không dùng nhiều agent.

```
Kênh (voice: Gemini Live | text: LLM) ─┐
                                       ▼
                    AgentSession (máy trạng thái: chào → chọn chế độ → luyện → tổng kết)
                       │        │            │              │
              ContextBuilder  ToolRegistry  Guardrails    Scaffolding
              (hồ sơ, nhật ký, (schema +     (đối số, nội  (phát hiện ngập
               vùng học, thẻ    kiểm quyền    dung, ngân    ngừng, gợi ý
               đến hạn, yêu     server)       sách)         tăng dần)
               cầu học)
                       │
                 Trace + sổ chi phí AI + ghi nhật ký (speaking_turn, speaking_session)
```

- **Một lõi, hai kênh.** `AgentSession` không biết kênh; voice và text là adapter. Gộp
  `companion.py` (theo lượt) và `realtime.py` vào lõi này; `companion/*` giữ làm kênh text
  (web dùng làm dự phòng khi giọng nói lỗi).
- **ContextBuilder** lắp ngữ cảnh gọn mỗi phiên: hồ sơ ngôn ngữ (profile snapshot), 20 việc gần
  nhất từ nhật ký, vùng học hiện tại (nếu có), thẻ đến hạn, yêu cầu học đang mở, tín hiệu cá nhân
  hóa. Phần chi tiết lấy bằng tool khi cần, không nhồi vào prompt.
- **Tool** (server kiểm mọi đối số, chỉ dữ liệu của người học đang nói):
  - đọc: `get_recent_activity`, `get_region`, `get_due_cards`, `get_study_requests`,
    `lookup_word`, `get_grammar_lesson`, `get_progress_summary`;
  - hiển thị: `show_hint`, `show_correction`, `explain_grammar`, `show_natural`,
    `show_suggestions`, `show_tasks`;
  - hành động (người học xác nhận trên màn hình khi đổi dữ liệu): `save_word`,
    `create_study_request`, `start_roleplay`, `offer_activity`, `note_interest`, `note_goal`, `remember`, `forget`;
    làm thay người học (giai đoạn 4): `open_review`, `open_video_region`, `edit_today`.
- **Vòng lặp agent (agent v2 giai đoạn 1, 2026-11-15, PRD 8.12; chỉ kênh chữ).** `agent/loop.py`: nhận phiên,
  system prompt, hội thoại (dạng message) và các `ToolSpec`; gọi model bằng function calling gốc
  (`ToolCallingModel.generate_with_tools` trong `platform/llm`, dùng chung sổ chi phí), chạy tool, trả kết quả
  cho model cho tới khi model trả lời bằng chữ, trong ngân sách `MAX_STEPS = 6` lần gọi (lần cuối không có tool) và
  `MAX_SECONDS = 12`. Mọi lời gọi tool vẫn qua `ToolRegistry.call` (kiểm đối số, chỉ đọc dữ liệu của chính người
  học, ghi cần xác nhận); tool hiển thị không cần nút bấm, và câu agent nói cũng
  qua `AgentSession.note_support` (quy tắc bằng chứng). Ngập ngừng đến agent như một sự kiện trong tin nhắn, agent
  chọn cách giúp; chính sách ngôn ngữ (dưới B1/HSK3 được giải thích bằng tiếng Việt, từ B1/HSK3 chỉ ngôn ngữ đang
  học) nằm trong prompt, và câu trả lời trượt ngôn ngữ hoặc quá dài bị trả lại cho agent hỏi lại trong cùng ngân
  sách thay vì kết thúc phiên. `evals.py` chạy các kịch bản cố định qua loop.
- **Kênh giọng nói theo cùng luật (agent v2 giai đoạn 2, 2026-11-15).** Ở giọng nói chính Gemini Live là vòng lặp
  (tự gọi tool), nên `loop.py` không dùng; dùng chung là luật, prompt và tool. `build_voice_instruction` dựng từ
  cùng khối với prompt chữ (`ROLE`, `language_policy`, `TOOL_RULES`, `SAFETY` trong `prompts.py`); chỉ phần nói
  (câu ngắn, không định dạng) và các tool riêng của giọng nói là riêng. Tool hiển thị không còn cờ nút; nút Gợi ý,
  Giải thích, Tự nhiên hơn, Ý tưởng gửi cho agent một tin ngắn "người học yêu cầu" (Gợi ý kèm mức gợi ý đã thấy).
  `Scaffolding` báo sự kiện ngập ngừng (im lặng, chỉ từ đệm, "không biết nói", số lần liên tiếp) và agent chọn cách
  giúp; tối đa 3 sự kiện mỗi câu hỏi. Đồng hồ im lặng 5 giây tính từ lúc ước tính người học nghe xong (thời điểm
  gửi khung âm thanh đầu của lượt + tổng độ dài âm thanh đã gửi, không sớm hơn turn-complete). Lượt sai ngôn ngữ
  theo chính sách bị trả lại cho agent nói lại; 3 lượt sai liên tiếp (`MAX_LANGUAGE_SLIPS`) thì kết thúc phiên
  (`policy`); nói về điểm số (`grading_claim`) vẫn kết thúc phiên ngay. Thẻ gợi ý hiện đúng phần agent đưa, `level`
  là mức suy từ các trường có mặt. Giao thức WebSocket với web không đổi. **Còn lại:** nối lại phiên Live bị rớt
  (trạng thái phiên ở server: xem giai đoạn 5 bên dưới).
- **Trí nhớ qua phiên (agent v2 giai đoạn 3, 2026-11-16, PRD 8.12 điểm 3; code written, tested locally; migration
  `20261116095000_agent_memory.sql` là bản nháp, chưa áp dụng).** Bảng `v3.learner_agent_memory` (`goal`, `interest`,
  `error`, `follow_up`; một câu ngắn ≤ 200 ký tự, `language_code` rỗng = mọi ngôn ngữ; tối đa 40 dòng mỗi người, dòng
  cũ nhất bị xóa trước; xóa theo tài khoản qua khóa ngoại `on delete cascade`). Tool `remember` (im lặng, tối đa 3
  mỗi cuộc, cắt/làm sạch như văn bản lưu khác) và `forget` (theo id agent thấy trong ngữ cảnh) cho cả hai kênh;
  `ContextBuilder` đọc tối đa 20 dòng một lần khi bắt đầu cuộc (kênh chữ: cache 60 giây) và `LearnerContext.render()`
  đưa khối "điều bạn nhớ" kèm id; lỗi đọc = không có khối, không hỏng cuộc nói. Người học xem và xóa trong Hồ sơ:
  `GET /learner/me/agent/memory`, `DELETE .../{memory_id}`, `DELETE .../memory`; có trong bản xuất dữ liệu. Prompt
  cấm lưu sức khỏe, tiền, chính trị, tôn giáo, giấy tờ, liên lạc, người khác (`MEMORY_RULES`). `evals.py`: 13 kịch bản.
- **Agent làm thay người học (agent v2 giai đoạn 4, 2026-11-15, PRD 8.12 điểm 4; code written, tested locally, không có
  migration).** Ba tool hành động cho cả hai kênh, mọi đối số do server kiểm, chỉ dữ liệu của chính người học, bị từ chối
  thì trả kết quả chứ không ném lỗi. `open_review` (tối đa 20 id lấy từ `get_due_cards`, server chỉ giữ id là từ đã lưu của
  người học trong ngôn ngữ này, hỏi qua `AgentFacts.owned_saved_ids` = truy vấn bộ thẻ `review_deck_cards` đã giới hạn theo
  người học và ngôn ngữ) và `open_video_region` (id video trong Thư viện của người học và mã vùng đúng dạng của video đó,
  `VideoRegions.check`; id lấy từ `get_region`) **chỉ chuẩn bị**: ra một thẻ hành động có một nút, web không tự chuyển
  trang vì rời màn agent là kết thúc cuộc nói chuyện. `edit_today` thêm hoặc bỏ một việc của kế hoạch hôm nay (loại
  `review`, `my_words`, `conversation`, `video_practice`; câu chữ cố định do server viết; không tạo kế hoạch mới, không gọi
  model) và **làm ngay**, tối đa 3 lần mỗi cuộc (bộ đếm giữ ở server cùng cuộc nói), thẻ kèm Hoàn tác đúng thay đổi đó
  (`POST /learner/me/plan/items/{id}/undo`, lặp lại vô hại). Một hình dạng sự kiện cho cả hai kênh:
  `{"type": "action", "action": "open_review" | "open_video_region" | "today_edited", ...}`; kênh chữ mang cùng dữ liệu
  trong `CompanionTurnView.actions` (danh sách, mặc định rỗng). `offer_activity` giữ cho điều hướng thường. Kênh chữ
  nhận thêm trường `request` (`hint` | `explain` | `natural` | `suggest`) ở `POST .../companion/turns`, kèm chữ hoặc
  không, đi vào agent bằng chính tin `learner_request` của kênh giọng nói; tối đa 20 lần mỗi cuộc (đếm ở server).
  Prompt giọng nói `agent-voice-v14`, chữ `agent-text-v7` (khối `ACTION_RULES`: chỉ khi người học muốn hoặc đồng ý bằng
  lời, không bịa id, một thẻ một lúc). `evals.py`: 15 kịch bản (thêm "ôn các từ đến hạn ngay" và "thêm ôn tập vào việc hôm
  nay"). Web mở vùng video qua `?region=<câu đầu>_<câu cuối>` của trang xem (lưu thành vùng học rồi tua tới câu đầu).
- **Trạng thái cuộc nói ở server, giới hạn dùng chung (agent v2 giai đoạn 5, 2026-11-15; code written, tested locally,
  không có migration).** Kênh chữ giữ cuộc nói trong một `SessionStore` (port ở `agent/ports.py`): `TextSession` gồm
  ngữ cảnh do server dựng, các message của vòng lặp kể cả lời gọi tool và kết quả của các lượt trước (tối đa
  `MAX_STATE_MESSAGE_CHARS = 48 000` ký tự: bỏ phần tool của lượt cũ trước, rồi bỏ lượt cũ nhất; lượt mở đầu và lượt
  mới nhất luôn giữ), trợ giúp đã hiện (`Scaffolding`: số lần ngập ngừng, mức gợi ý đã thấy, số lần bấm Gợi ý, nên
  yêu cầu Gợi ý ở kênh chữ báo đúng mức đã thấy như kênh giọng nói), các bộ đếm mỗi cuộc và hỗ trợ đã đưa (bằng chứng
  FR-3.5); không có âm thanh. Vé `session_ticket` (tên và kiểu chuỗi với web không đổi) chỉ còn là tham chiếu ký HMAC:
  id cuộc nói, người học, id vé dùng một lần, hạn = hạn cuộc nói (tối đa 15 phút từ lúc bắt đầu, như trước). Mỗi lượt
  thành công "nhận" id vé trong store (một lệnh nguyên tử) và cấp vé mới; vé cũ, vé của người khác, cuộc đã hết hạn
  hoặc đã kết thúc trả `companion_session_invalid` như cũ. Kết thúc cuộc, cuộc tự kết thúc hoặc người học rút đồng ý
  giọng nói thì trạng thái bị xóa ngay. Hai nơi lưu: bộ nhớ của một tiến trình API (có hạn, có giới hạn số mục; mặc
  định và trong test) và Redis. Trạng thái có chữ của người học nên chỉ vào Redis không lưu đĩa
  `COMPANION_SESSION_TEXT_REDIS_URL` (kiểm `appendonly`/`save`/replica trước mỗi lần ghi, giống văn bản L2), khóa
  `deeplingo:agent:conversation:<người học>:<id>` có TTL; store lỗi = `companion_unavailable` (web đã xử lý), không
  bao giờ âm thầm mở cuộc mới. `RealtimeGate` (số phiên giọng nói đồng thời, giây mỗi người mỗi ngày UTC) và
  `SlidingWindowLimiter` (giới hạn yêu cầu) đếm trong một store: bộ nhớ tiến trình, hoặc Redis của `REDIS_URL` khi
  có (chỉ số đếm; khởi động lại không mất giây đã dùng trong ngày, nhiều tiến trình API đếm chung; lệnh nguyên tử
  hoặc MULTI/EXEC, phiên mở cùng lúc không vượt hạn mức ngày). Redis không tới được thì: cổng giọng nói **đóng** (từ
  chối phiên mới bằng `realtime_unavailable`), giới hạn yêu cầu **mở về bộ đếm của tiến trình** (vẫn giới hạn, theo
  từng tiến trình), kho cuộc nói chữ báo `companion_unavailable`.
- **Sửa ngữ pháp → yêu cầu học.** Khi `show_correction` gắn với một điểm ngữ pháp trong bank, lõi
  tạo `grammar_redo` (gộp trùng trong 7 ngày) và agent nói ngắn rằng bài đã được thêm vào Sổ tay.
- **Guardrails.** Kiểm schema và quyền của tool; kiểm transcript sau mỗi lượt (đã có); giới hạn
  thời lượng và ngân sách theo người học (đã có); không lưu âm thanh.
- **Eval.** Bộ kịch bản cố định (A1/HSK1, ngập ngừng, sai ngữ pháp, lạc đề, đóng vai) chạy với
  model giả trong test thường; một bộ nhỏ chạy với model thật khi đổi prompt hoặc tool, có trần
  chi phí. Chỉ số: đúng tool, đúng mức gợi ý, không lộ dữ liệu người khác, độ trễ.
- **Cờ cấu hình.** Bỏ các cờ đang tắt (`COMPANION_PROFILE_BRIEF`, `COMPANION_GRAMMAR_LESSONS`,
  `COMPANION_SESSION_EVENTS_ENABLED`) bằng cách đưa hành vi vào lõi; `COMPANION_REALTIME_ENABLED`
  thay bằng cấu hình kênh.

**Xóa trong GĐ4.** `companion.py`, `realtime.py` cũ, `companion_*`, `speaking_*` trùng chức năng,
`HELP_CUES` dạng chuỗi trong service, màn `CompanionScreen` riêng, chế độ `mode=conversation`.

**Xong khi.** Eval giả xanh trong CI; phiên voice và text đi cùng lõi; gợi mở tự kích ở 5 giây;
sửa ngữ pháp tạo đúng một yêu cầu học; agent trả lời đúng câu hỏi "hôm qua tôi học gì" từ nhật ký.

## 8. Giai đoạn 5 — Tiến bộ (XONG 2026-11-14, nhánh `feat/progress`)

`GET /learner/me/progress?language=` trả: chuỗi ngày học (ngày có ít nhất một dòng nhật ký), heatmap,
số thẻ theo trạng thái FSRS, độ chính xác theo loại bài, điểm phát âm theo ngày, điểm ngữ pháp đã
học/đã làm đúng, số vùng học đã xong, số phút nói. Web hiện bộ lọc ngôn ngữ; Home dùng cùng
endpoint cho thẻ tóm tắt.

**Đã làm (2026-11-14).** Module `progress` và endpoint trên; web Tiến bộ, Home và Tài khoản đọc endpoint này; mã web chỉ phục vụ lịch cũ (đọc `activity-calendar`, `progress/pronunciation`, biểu đồ từ đến hạn) đã xóa. `activity-calendar`, `progress/pronunciation` và route `review-forecast` đã xóa 2026-11-15.

**Xóa trong GĐ5.** `activity-calendar`, `progress/pronunciation`, `review-forecast` (đã xóa 2026-11-15), các truy vấn tiến bộ riêng lẻ.

**Xong khi.** Số liệu khớp nhật ký trong test; lọc ngôn ngữ đúng; E2E trang Tiến bộ.

## 9. Việc chung cho mọi giai đoạn

- **Test:** một bộ fake dùng chung cho repository; bỏ dần test đọc mã nguồn; mỗi luồng một test
  hành vi và một E2E tất định.
- **Migration:** mỗi giai đoạn tối đa một file migration; áp lên dev cần duyệt; cuối GĐ5 gộp baseline.
- **Đo:** ghi số dòng code backend/web trước và sau mỗi giai đoạn trong mô tả PR.
