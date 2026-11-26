# DeepLingo status

Tệp trạng thái duy nhất (xem AGENTS.md): chỉ ghi trạng thái hiện tại, không ghi nhật ký. Bằng chứng từng đợt (lệnh, số đếm, mã băm, biên nhận deploy) nằm trong commit message và mô tả PR. Bản dài theo từng đợt nằm trong git: `git show 2208706:docs/product/STATUS.md`. ADR, kiến trúc và kế hoạch sản phẩm trước tái thiết kế: `git show 2b67a0a:<đường dẫn cũ>`.

Sản phẩm là gì, yêu cầu và quyết định của chủ dự án: [PRD.md](PRD.md). Tệp này chỉ ghi hiện trạng.

Thuật ngữ: **code written** (đã viết code), **tested locally** (đã chạy test ở máy hoặc CI, dữ liệu giả), **verified in a real environment** (đã chạy ở môi trường thật).

## Đang chạy trên development (không phải production)

Mốc mới nhất (2026-11-19, chủ dự án duyệt): `main` `afecfac2`. Mã đang chạy là backend `6c683240` và web `049246b9`; các commit sau chỉ sửa file migration và tài liệu, không đổi mã chạy.
- Backend: ảnh `e0ec7de56a08` cho API, worker và Beat. `rollout.py verify` đạt (nguồn khớp từng byte, health 200, worker ping, một Beat, giữ `AGENT_CHANNELS=text,voice`). Redis đang đếm trần chi tiêu AI (2 USD mỗi ngày).
- Web Firebase Hosting `project-c9cce631-2bba-4b32-a76`: phiên bản `3da3c0854b7eac62` (bản trước `8b087b6aeed894fd` để quay lại); `verify_public.py` đạt. Đã mở Home, Tiến bộ, Hồ sơ và màn Tata bằng Chrome đã đăng nhập: tải đúng, không có lỗi tải.
- Chưa kiểm: nút "Cần luyện lại" với dữ liệu thật (chưa có yêu cầu học), nói thật với Tata (thời gian nói theo cách đo mới và bộ đếm trần với một phiên Live thật), điện thoại thật.
- API `https://34-143-205-183.sslip.io/api/v1/v3` (VM `deeplingo-vm`, `asia-southeast1-c`, vào qua `gcloud compute start-iap-tunnel` và OpenSSH). Chỉ IP tester của chủ dự án vào được API, IP khác nhận 403; danh sách là dòng `@tester remote_ip` trong Caddyfile của VM. Khi IP đổi thì web tải được nhưng API bị chặn.
- Giọng nói (Live): `Cần kiểm lại`. Một đoạn ghi Live tắt và danh sách người dùng cho phép rỗng; đoạn khác ghi Live bật cho tài khoản của chủ dự án từ 2026-11-09 và API chạy với `AGENT_CHANNELS=text,voice`. Chưa thử bằng giọng người thật.
- Flutter (`deeplingo_app`): đã bỏ khỏi kho (xem "Đợt thu gọn" bên dưới).

**Supabase development, 2026-11-23 (chủ dự án duyệt).** Ledger khớp 123 phiên bản trong nhánh
`codex/backend-audit-followup` và hai ràng buộc FSRS đã được xác thực (**verified in a real environment**).
Bốn migration `record_personalization_signal`, `review_usage_evidence`, `atomic_primary_language_profile`
và `learner_profile_metrics` còn chờ áp. Các mã ledger trong
mốc lịch sử bên dưới là mã dùng tại thời điểm áp migration.

## Đợt thu gọn 2026-11-15 (đã gộp vào `main`; deploy development 2026-11-16)

Ba nhánh từ `a18ce176`: `refactor/slim-backend`, `refactor/slim-web`, `chore/status-trim`. **Code written**, **tested locally**:
- Backend: `python -m pytest -q` đạt 2061, bỏ qua 1 (trước đợt: 2478; số giảm là test của code đã xóa). Bỏ app Flutter, engine phiên học cũ, module `assessment`, 13 route không client nào gọi, tính năng "bỏ qua từ". Code backend khoảng 38.000 → 32.000 dòng; 105 → 90 route.
- Web: `npm run typecheck`, `npm run lint`, `npm test` (561 đạt) và `npm run build` đạt. Bỏ file và CSS chết (`styles.css` 2.330 → 1.886 dòng), bỏ phần "Thêm lại" ở Sổ tay. Bộ E2E tất định chạy một lần trước khi bỏ "Thêm lại": 256/257, ca trượt đạt khi chạy riêng; chưa chạy lại sau đó. Chưa có so sánh ảnh chụp.
- Migration trên Supabase development `sqlcckgdfxyrepqawahn`, **verified in a real environment** (kiểm catalog sau khi áp): đã áp cả bốn file nháp `20261116091000`, `…092000`, `…094000`, `…095000` (bảng trí nhớ `v3.learner_agent_memory` có mặt) cùng hai file trước đó `…090000` và `…093000`. Đã mất: bảng phiên học cũ (31 phiên, 39 hoạt động, 18 bài làm, 9 kết quả ngữ pháp cũ) và bảng "bỏ qua từ" (rỗng). Cột `self_usage` và `learning_objects.supported_activity_types` đã bỏ.
- Dọn sót sau đợt thu gọn (2026-11-16): xóa script smoke Quick review cũ và harness `runHarness`/`quickReview`, bỏ mock của endpoint đã xóa trong test e2e, sửa `e2e_learner.py` cho đúng bảng hiện tại, sửa chú thích còn nhắc Flutter/known check. **Tested locally** (xem PR). Chủ dự án chốt 2026-11-16 bỏ hẳn "đã biết" (8.8): mã backend và web đã bỏ (PR #120). Đã deploy development 2026-11-16: backend image `28c4bc8638f9` (commit `099fac3a`; `rollout.py verify` đạt) và web Firebase `de27c3b8b8e1dd27` (`verify_public.py` đạt). Migration `20261116100000` đã áp trên Supabase development: bảng `learner_known_concepts` đã xóa, bảy hàm SQL không còn nhắc nó, gọi thử `review_deck_counts`, `review_deck_cards`, `review_answer_context` đều chạy (**verified in a real environment**, chưa có người học thật dùng).
- Gộp CSS web (2026-11-16): bỏ `styles.css` (1.886 dòng); 285 khối quy tắc dùng chung chuyển lên đầu `design/components.css`, 35 khối chỉ một màn dùng chuyển vào `watch.css`, `home.css`, `account.css`; bỏ 4 quy tắc và 1 keyframe không còn ai dùng; nút "Retry suggestions" ở Home có kiểu `dl-btn--secondary`. **Tested locally**: 170 ảnh chụp (17 màn × 10 kích thước, Chromium, tối và sáng) so với trước khi đổi không khác về kiểu dáng (khác biệt còn lại là trạng thái tải dữ liệu, xuất hiện cả khi chạy lại mã cũ), `typecheck`, `lint`, `npm test` 596, `build`, `check:bundle` 113,8 KiB, E2E tất định 257/257. Chưa deploy.
- Kho: còn 6 worktree và 6 nhánh local. Phần chưa gộp của các worktree và nhánh đã xóa được sao lưu ở `D:\DeepLingo-archive\2026-11-15` (patch, tệp chưa theo dõi, bundle ba nhánh chưa gộp, tệp môi trường build web).

## Rà soát codebase 2026-11-18 (nhánh `chore/audit-cleanup`, chưa gộp)

- Đã xóa phần không còn ai dùng: route `POST .../session-summary` cùng service, test và phần đọc lại nhật ký luyện chỉ nó dùng (web đã bỏ tính năng này); `app/kernel/activity_types.py`; enum `CompanionNext`, `MasteryDimension`; protocol `LearningObjectReader`; hai hàm đọc của repository không ai gọi; fixture của engine phiên cũ trong web; hàm `isNotebookScope`; 312 khóa tiếng Việt không còn chuỗi nào dùng; `design-system/deeplingo-web/MASTER.md` (mô tả `styles.css` đã xóa). **Tested locally:** backend `pytest` 2188 đạt, 1 bỏ qua; web typecheck, lint, `npm test` 598, build, `audit:build`, `check:bundle` 113,8 KiB, E2E tất định 257/257.
- Database development (truy vấn chỉ đọc): 55 bảng trong `v3`, bảng nào cũng có code hoặc hàm SQL dùng. Chồng chéo còn lại là việc của chủ dự án: nhật ký học tập nằm ở năm bảng (`learner_activity_log`, `learner_practice_events`, `learner_speaking_activity`, `speaking_sessions`, `target_events`). Yêu cầu học: `grammar_redo` hiện trong danh sách "Cần làm lại" ở tab Ngữ pháp của Sổ tay (qua endpoint ngữ pháp) và tự đóng khi làm đúng; `word_review` chỉ hiện thành thẻ trong hội thoại; Home không hiện yêu cầu học; web không gọi route `study-requests` (danh sách, bỏ qua). Hai loại `pronunciation_retry`, `region_practice` có trong schema nhưng không có code tạo.

## Đợt 2026-11-18 (chủ dự án duyệt làm hết)

- **Yêu cầu học trong màn Tata (PR #128):** chip "Cần luyện lại (n)" cạnh nút đóng, chỉ hiện khi có yêu cầu mở; danh sách gọn có tên từ hoặc điểm ngữ pháp, nút "Luyện" cho ngữ pháp và nút bỏ qua. Route mới `GET /learner/me/agent/study-requests` thay route danh sách cũ. **Tested locally** (backend 2191 đạt; web E2E 259/259, có ảnh chụp 390 và 1280px).
- **Migration đã áp trên Supabase development 2026-11-18** (chủ dự án duyệt): `20261117090000_agent_memory_add` (ledger `20261118040419`; thử trong khối tự hoàn tác: 41 lần thêm còn 40 dòng, bỏ dòng cũ nhất) và `20261118090000_backend_only_writes_and_fk_indexes` (ledger `20261118040455`): `authenticated` không còn quyền ghi bảng nào, policy của bốn bảng chỉ còn đọc của chủ, thêm 13 index cho khóa ngoại có xóa dây chuyền (15 khóa trỏ tới `languages` để nguyên). **Verified in a real environment** ở mức catalog.
- **Deploy development 2026-11-18** (chủ dự án duyệt) từ `main` `b64754b6` (PR #125–#128): backend image `ba06e6ce4bc6` (`rollout.py` build, deploy, verify đạt; Beat một container; `REDIS_URL` và `COMPANION_SESSION_TEXT_REDIS_URL` có trong API); web Firebase `8b087b6aeed894fd` thay `e02cc247c8c60b9e` (`verify_public.py` đạt). Gọi `LearnerFacts.open_requests` trong container chạy; route mới trả 401 khi chưa đăng nhập. **Verified in a real environment** ở mức máy chủ và file công khai; chưa mở giao diện bằng tài khoản người học.
- **Không đổi, có lý do:** các lần ghi còn lại trong vòng lặp agent đều chống trùng khi thử lại (thêm việc hôm nay bị từ chối nếu đã có, nhật ký nhập vai có khóa sự kiện, yêu cầu học chống trùng 7 ngày); chỉ "bỏ việc" khi có hai việc cùng loại có thể bỏ thêm một việc nếu lượt lỗi rồi thử lại.

## Đợt 2026-11-19 (chủ dự án giao tự quyết: nhật ký, thời gian nói, trần AI, lớp phủ mobile)

- **Một nhật ký học tập (PR #130):** `learner_practice_events` và `learner_speaking_activity` đã gộp vào `learner_activity_log` rồi xóa; mọi luồng chỉ ghi nhật ký. `speaking_sessions` và `target_events` giữ riêng (không phải việc người học làm; gộp sẽ tính một phiên nói hai lần). **Tested locally** (backend 2189 đạt). Đã deploy development từ `main` `6c683240` (image `e0ec7de56a08`, `rollout.py verify` đạt) rồi áp migration `20261118100000` (ledger `20261118223111`), chủ dự án duyệt: 15 dòng luyện tập được chép, hai bảng cũ đã xóa (**verified in a real environment** ở mức catalog). **Lỗi của migration:** mốc cắt của lệnh chép phiên nói được tính sau khi lệnh chép đầu đã thêm các dòng cũ hơn, nên 6 phiên nói cũ trên development (dữ liệu thử của chủ dự án, 8–15/11) không được chép và đã mất cùng bảng; không ảnh hưởng người dùng thật. Đã sửa file migration (hai lệnh chép đổi thứ tự: phiên nói chép trước, nên mốc cắt là dòng cũ nhất thật của nhật ký) và thêm test; development đã áp bản cũ nên 6 phiên đó không lấy lại được. Môi trường áp sau dùng bản đã sửa.
- **Thời gian nói là phút bạn thật sự nói (PR #130):** kênh giọng cộng phần có tiếng nói của từng lượt như kênh chữ.
- **Trần chi tiêu AI 2 USD mỗi ngày (PR #131, `AI_DAILY_BUDGET_USD`):** đếm ước tính trong Redis; kiểm trong container development: bộ đếm dùng Redis, trần 2,0 và tăng khi ghi. Giá là giá niêm yết (Azure từ nguồn thứ ba); xem lại khi có người dùng thật.
- **Web deploy development 2026-11-19** từ `main` `049246b9` (PR #130–#132, chủ dự án duyệt): Firebase `3da3c0854b7eac62` thay `8b087b6aeed894fd`, `verify_public.py` đạt; build 114,2 KiB (`check:bundle` đạt). Chưa mở giao diện bằng tài khoản người học. 32 đến 67 ảnh responsive khác mốc sau khi bỏ CSS thừa là trạng thái đang tải chụp lệch thời điểm (đã xem Profile và Agent); chưa xem hết từng ảnh.
- **Lớp phủ mobile và CSS thừa (PR #132):** đo 510 tổ hợp, không nút nào bị che vĩnh viễn; sửa thanh Tata che ô Translation ở Watch; bộ responsive báo lỗi nếu một điều khiển bị che ở cả hai đầu trang; bỏ 116 selector CSS không dùng.

### Tổng kết 2026-11-17 đến 19
- **Đã gộp và deploy development:** hàm SQL tổng hợp tiến bộ (#122); gộp style và dọn CSS (#123, #132); trí nhớ agent chỉ ghi sau khi lượt thành công (#125); sửa Tiến bộ và nhãn xóa tín hiệu (#126); dọn code thừa (#127); yêu cầu học nằm trong màn Tata (#128); thu hồi quyền ghi và thêm index (#129); một nhật ký học tập và thời gian nói là phút thật sự nói (#130); trần chi tiêu AI (#131); sửa mốc cắt migration (#134).
- **Còn lại, cần chủ dự án hoặc người dùng thật:** thử nói thật và điện thoại thật; xem lại trần 2 USD và giá Azure khi có dữ liệu dùng thật; khoảng 67 ảnh responsive khác mốc sau khi bỏ CSS thừa chưa xem hết từng ảnh; ca unit "Start talking" ở `workspace.test.tsx` đôi khi trượt khi máy tải nặng (CI vẫn đạt); phát âm Azure và pháp lý bộ từ như mục "Chưa kiểm chứng".

## Nhánh `feat/agent-harness` (PR #141, 2026-11-22; đã deploy development)

**Deploy development 2026-11-22 (chủ dự án duyệt), verified in a real environment ở mức máy chủ:** backend `e07477b2` image `91de142b2e5d` (`rollout.py` build, deploy, verify đạt; nguồn khớp từng byte; một Beat), web Firebase `3cad386f7b843544` (bản trước `07599feb4c0fb32d`; `verify_public.py` đạt, 98 file khớp). Migration `20261122100000_agent_memory_evidence` đã áp trên Supabase development (ledger `20261122071010`): có hai cột `evidence`, `source`; hàm `add_agent_memory_with_evidence` chỉ `service_role` gọi được; trong container, bộ hợp nhất có mặt và đọc được cột mới. Một phiên Live thật bằng Chrome đã đăng nhập: mở được với cấu hình session resumption, agent trả lời bằng prompt `agent-voice-v16`, kết thúc `learner_ended`, `resumes=0` (phiên ngắn, chưa gặp `goAway`). **Kiểm tiếp 2026-11-22 trên development (verified in a real environment):** (1) nối lại phiên Gemini: trong container, `ResumableConnection` với Vertex thật; sau khi kết nối bị đóng, phiên tiếp tục trên kết nối mới bằng handle (mở lại 1,7 s) và model vẫn nhớ chi tiết đã được kể trước đó; tiếng nói của lượt sau có sau 0,65 s. (2) Gắn lại socket: lần đầu thất bại (4404) vì API tạo `VoiceChannel` mới cho mỗi WebSocket; đã sửa ở PR #142 (danh sách phiên ở mức tiến trình), deploy backend `7965cef9` (image `71b1a052a169`, `rollout.py verify` đạt). Kiểm lại: socket mới nhận bù sự kiện đã lỡ, bấm Gợi ý thì có thẻ gợi ý và tiếng sau 1,8 s, trace `reattaches=1`, kết thúc `learner_ended`. (3) Kênh chữ `/turns/stream` (tài khoản chủ dự án, gõ chữ): chữ trả lời đến sau 1,9 s và 2,9 s, câu tiếng đầu sau 2,2 s và 3,2 s; endpoint cũ `/turns` cả lượt mất 2,2 s và 3,1 s, nên với câu trả lời ngắn lợi ích chỉ khoảng 0,2–0,3 s. (4) Live: sau một gợi ý mở đầu, tiếng đầu tiên sau 0,7–1,0 s; lời chào đầu tiên sau 4,4–8,0 s tính từ lúc mở socket (gồm xác thực, dựng ngữ cảnh và mở phiên Gemini). (5) Bộ hợp nhất trí nhớ với model thật (ghi vào bộ nhớ giả): 3 ghi chú đúng, mỗi ghi chú trỏ đúng lượt làm bằng chứng, bỏ một mục tiêu cũ mâu thuẫn, không đề xuất nào bị từ chối. (6) Hàm SQL `add_agent_memory_with_evidence` chạy trong transaction rồi rollback: ghi đúng nguồn và bằng chứng, không còn dòng thừa. Chưa kiểm: `goAway` thật (cần phiên dài khoảng 10 phút), hợp nhất trí nhớ từ một phiên giọng nói thật có bật đồng ý lưu bản ghi, `latency_probe.py` với giọng nói thu sẵn.



Khung bao quanh agent theo kế hoạch 8 giai đoạn (PRD 8.12), thêm tóm tắt lịch sử dài và bậc dùng từ trong thẻ ôn. **Code written, tested locally**: backend `pytest` 2283 đạt, 1 bỏ qua (gồm `tests/architecture`); web `typecheck`, `lint`, `npm test` 620 đạt. **Chạy với model thật ở máy (2026-11-22, chưa deploy):** prompt `agent-voice-v16` / `agent-text-v10` (khi bí luôn có ít nhất câu hỏi gợi ý trên màn hình, không hỏi lại câu đã được trả lời, nêu điều cụ thể từ kết quả tool, gắn với mục tiêu đã nhớ). Trước khi sửa: `eval_live.py` 12/15, `eval_dialogues.py` 5/6. Sau khi sửa: lần chạy cuối `eval_live.py` 14/15 và `eval_dialogues.py` 5/6. Cả hai lần trượt (`uses_memory`, `hsk1_zh`) đều đạt khi chạy riêng lại (lần lượt 3/3 và 2/2), nên là do model không ổn định giữa các lần chạy. Tổng chi phí ước tính khoảng 0,6 USD. **Chưa verified in a real environment**: chưa chạy `latency_probe.py` (cần bản deploy), chưa thử session resumption với Vertex, chưa áp migration `20261122100000_agent_memory_evidence.sql` (nháp; khi chưa áp, trí nhớ chạy như trước nhưng không có bằng chứng).

## Nhánh `fix/occurrence-word-boundary` (2026-11-20, chưa gộp)

- Chọn ngữ pháp: với ngôn ngữ có dấu cách, mẫu ngữ pháp chỉ gắn vào từ trọn vẹn trong câu trích; trước đây mẫu "a" gắn vào chữ "a" trong "at" (video "broken heart", "looking at a photo") làm chữ bị tách đôi trên bản ghi. Không có từ trọn vẹn thì bỏ mẫu và ghi lỗi. Tiếng Trung giữ cách khớp cũ. **Tested locally** (backend 2234 đạt, 1 bỏ qua). Dữ liệu đã chuẩn bị trước bản sửa không tự đổi.

## Nhánh `fix/region-preparation-model-errors` (2026-11-20, đã gộp PR #139; đã deploy development)

- Chuẩn bị đoạn học: một phản hồi Gemini sai định dạng, rỗng hoặc bị từ chối cho một từ chỉ làm hỏng từ đó, không còn làm đoạn thất bại vĩnh viễn (trên development, đoạn 21–38 của video "broken heart" hỏng vì một phản hồi `provider_schema_violation`). Lỗi mạng, cấu hình, ngân sách vẫn làm cả đoạn thử lại. Sinh câu hỏi theo đoạn ghi log số câu bị loại theo lý do (không ghi nội dung). **Tested locally** (backend 2233 đạt, 1 bỏ qua).
- Development (chủ dự án duyệt): backend commit `ff1e805c`, image `ae16dbc1487a`, `rollout.py build`, `deploy`, `verify` đạt. **Verified in a real environment**: đoạn 4 của cùng video chuẩn bị xong, `questions=ready proposed=3 kept=3 rejected=-`. Nhánh sửa lỗi phản hồi hỏng chưa được gặp lại trên development.
- Chưa giải quyết: đoạn 11–20 trước đó ra `questions_status=none` (`proposed=1 kept=0`), lý do loại chưa biết (log mới sẽ ghi khi gặp lại). Đổi `region_questions_v1` sang `v2` làm mọi đoạn đã chuẩn bị bằng v1 thành `not_prepared` cho tới khi người học chọn lại đoạn; có tự chuẩn bị lại hay không là quyết định của chủ dự án.

## Nhánh `fix/phrase-concept-and-grammar-503` (2026-11-19, chưa gộp; đã deploy development)

- Bấm cụm có nhiều nghĩa trên cùng khoảng (ví dụ "heart broken") mở một learning object thay vì nối id bằng `|` (trước đây trả 422). Grammar 503 chưa rõ nguyên nhân; service giờ log loại lỗi và category (không ghi nội dung). **Tested locally** (web 613, backend 2230 đạt).
- Development (chủ dự án duyệt): backend commit `0fbe36c1`, image `0554dd0a91b1`, `rollout.py build`, `deploy`, `verify` đạt; web version `07599feb4c0fb32d`, `verify_public.py` đạt (bỏ kiểm `/activity` vì route đã gỡ ở `4c600c31`). Bản này kèm PR #137 (đã gộp). Chưa bấm thử bằng tài khoản người học.

## Nhánh `fix/p0-review-findings` (2026-11-19, chưa gộp; đã deploy development)

**Code written**, **tested locally** (backend `pytest` và `lint-imports` đạt, web typecheck, lint, test, build đạt; số đếm ở mô tả PR). Sửa các lỗi rà soát: câu trả lời đúng chỉ đóng yêu cầu `word_review`; kênh giọng không còn gọi store đồng bộ trên event loop và trả đúng chỗ của phiên khi hai phiên đóng lệch thứ tự; bộ kiểm kiến trúc quét đệ quy và hợp đồng DAG đủ; đọc lớn đi qua trang 1000 dòng của PostgREST; số thẻ đến hạn của kế hoạch chỉ tính đúng ngôn ngữ; xóa trí nhớ agent làm mới ngữ cảnh đã nhớ đệm; một `httpx.Client` dùng chung; web: liên kết hội thoại về route `/agent`, thanh Tata không che màn ôn, thanh chọn không đè nút Tata, `?tab=grammar` theo đổi query, `lang` của trang, tiếng Việt cho bản tóm tắt phiên, màu biểu đồ thành token, `useContainer` đúng quy tắc hook; bỏ 4 route, `example_practice.py`, một biến cấu hình và vài CSS không ai dùng.
- **Development (2026-11-19, chủ dự án duyệt):** áp `20261119100000_review_closes_word_review_only` (ledger `20261119021131`) và `20261119110000_indexes` (ledger `20261119021142`); deploy backend từ nhánh `b6328807` (image `067f9d758b78`, `rollout.py build`, `deploy`, `verify` đạt, health 200, không có ERROR trong log); rồi áp `20261119120000_drop_looked_up_concepts` (ledger `20261119021812`, mất 5 dòng thử của 1 người dùng). **Verified in a real environment** ở mức catalog: hàm chỉ đổi điều kiện `kind = 'word_review'` (so md5 với bản trước), quyền chỉ cho `service_role`, 3 index mới có, 7 index trùng đã bỏ, bảng và hàm ghi đã bỏ, hàm purge còn. Chưa chạy luồng người học đầu-cuối; web chưa deploy lại. Development đang chạy code chưa gộp vào `main`.
- `migrations_archive/` giữ file migration gốc đã hỏng `20261001041627` để tra cứu.

## Agent v2 (PRD 8.12; 2026-11-15 đến 2026-11-16)

- **Tracing Langfuse cho kênh chữ:** **code written**, **tested locally** với client giả. Tracing và gửi nội dung đều tắt mặc định.
- **Toàn vẹn trí nhớ (nhánh `fix/agent-memory-integrity`, 2026-11-17):** kênh chữ trước đây ghi trí nhớ ngay trong vòng lặp agent, trước khi lượt thành công, nên lượt báo lỗi vẫn để lại bản ghi và lần thử lại ghi thêm. Giờ `remember` và `forget` của kênh chữ chỉ ghi vào hàng đợi trong phiên và được áp sau khi vé của lượt đã dùng và sự đồng ý còn hiệu lực (`ToolRegistry.commit_memory`); `forget` chỉ nhận id agent đã được cho xem. Thêm trí nhớ đi qua hàm SQL `v3.add_agent_memory` (migration `20261117090000`: thêm rồi cắt còn 40 dòng trong một giao dịch, khóa theo người học). **Code written**, **tested locally** (backend 2202 đạt, 1 bỏ qua; có test thất bại trước khi sửa cho lượt lỗi, đồng ý bị thu hồi giữa chừng và `forget`). Chưa áp migration lên development, chưa deploy; migration phải áp trước khi deploy backend. Chưa kiểm hàm SQL trên PostgreSQL thật. Các tool khác ghi ngay trong vòng lặp (sửa kế hoạch hôm nay, ghi nhật ký nhập vai) chưa đổi.
- **Prompt (2026-11-16, commit `6e5719b8`, deploy development, verified):** checklist trước mỗi lượt chữ (show_natural, giải thích tiếng Việt ở A1–A2, dùng điều đã nhớ). Bộ chấm thật trên dev: 13/15. `uses_memory` vẫn trượt (model không dùng mục tiêu đã nhớ); `yesterday` dao động. Kênh giọng nói chưa đổi.

Năm giai đoạn: **code written**, **tested locally** (backend 2192 đạt, 1 bỏ qua; `tests/architecture` 102 đạt; web 629 đạt). Đã gộp vào `main` (PR #115) và deploy development: backend image `fe5fa1b1a5f4` (commit `9bfb48ea`), web `582de8d25bc1a1b1`.
- **Bộ chấm thật** (`scripts/agent/eval_live.py`, gemini-3.5-flash-lite, trần 2 USD, chi phí ước tính 0,054 USD): **12/15 đạt**. Lần đầu 5/15 vì model gọi tool bị từ chối (HTTP 400, thiếu chữ ký suy nghĩ của Gemini 3); đã sửa ở `9bfb48ea`.
- Ba kịch bản còn trượt là chất lượng hành vi, chưa sửa: không gọi `show_natural` khi câu chưa tự nhiên; giải thích A1 bằng tiếng Anh thay vì tiếng Việt; không dùng điều đã nhớ về mục tiêu.
- **Chưa kiểm:** giọng nói thật, trình duyệt, Redis thật, nhiều tiến trình API. Thông báo quyền riêng tư chưa nói về trí nhớ của agent (**Cần chốt**).

## Hiện trạng từng mảng

Chuẩn bị phần học và video:
- Sửa `enrich_claimed_occurrence` tra từ điển bằng khóa chính (trước đó khoảng 4,5 s): **tested locally**; trên development 31/31 lời gọi trả 200, trung bình 7,7 ms; hai phần học lỗi đã chạy lại và `ready`. Chưa **verified in a real environment** bởi người học.
- Celery Beat trước đây chưa từng chạy ở dự án `deeplingo-m1-acceptance`, nay đã chạy. Sau lần quét đầu, 2 vùng học `failed` sau 3 lần thử và 4 vùng còn đang chạy hoặc chờ thử lại.
- Màn Video (đoạn phát Dictation/Shadowing đúng câu, thẻ kết quả trong khung phải, thanh Tata "Nói về đoạn N"), bản dịch câu bằng AI, thẻ kết quả vùng: **code written**, **tested locally** với dữ liệu giả; chưa gọi AI thật.

Sổ tay và ôn tập (web):
- Một engine ôn tập (`practice`): sáu loại bài cho từ, bộ thẻ theo ngôn ngữ, FSRS đổi lịch tối đa một lần mỗi thẻ mỗi lượt, ngữ pháp không dùng FSRS. Migration đã áp, chỉ **verified in a real environment** phần schema.
- Đơn giản hóa Sổ tay (bỏ đánh giá "Dùng được", bỏ luyện viết chữ Latin, Tập viết chữ Hán theo Hanzii): đã deploy; **tested locally**. Cột `saved_concepts.self_usage` và trường `self_usage` trong phản hồi đã bỏ (migration `20261116092000` đã áp trên development).
- Phần còn lại của Sổ tay (kệ, trang sổ tay, thẻ ghi nhớ, tab Ngữ pháp, tra cụm, thẻ Home heatmap): **tested locally** với dữ liệu giả và đã deploy; chưa người học thật dùng. Chưa chứng minh: đánh giá ghi nhớ, âm thanh từ Azure, ảnh Openverse, micro, dữ liệu nét hanzi-writer. Prompt `word_lookup_sense_v2` chưa thử với model thật.
- Điền chỗ trống: AI viết câu cho từ chưa có câu, đã deploy, mới thử với model giả.

Agent và giọng nói:
- Lõi agent (`learning/application/agent/`) cho kênh giọng nói và chữ, đọc nhật ký học tập, tự gợi mở khi ngập ngừng, Tata chào rồi hỏi người học muốn làm gì; một consent giọng nói có thể thu hồi, tín hiệu cá nhân hóa dạng mã đóng, agent chọn từ, tóm tắt cuối phiên, chấm phát âm Azure từng lượt (audio chỉ giữ trong bộ nhớ): **code written**, **tested locally** với AI, Azure, DB giả; đã deploy. Eval thật một lượt 2026-11-14 (`gemini-3.5-flash-lite`, dữ liệu giả): 7/7 kịch bản đạt, ước tính dưới 0,02 USD.
- Cuộc thử giọng 2026-10-30 (cap 1,00 USD): sáu phiên Gemini Live qua web thật, giọng Azure tổng hợp, tiếng Anh và tiếng Trung, **verified in a real environment** (không phải giọng người). Đã tìm và sửa lỗi phân tích tiếng Trung (PR #48).
- Hồ sơ người học dạng chỉ-đọc cho agent và gợi ý bài ngữ pháp đã duyệt: **code written**, **tested locally**; thử mô hình 2026-11-03 bằng văn bản tổng hợp; chưa thử qua app hay giọng thật. Bank A1 và HSK1 chưa có bài đã duyệt.
- Bản ghi lời nói có đồng ý riêng (PRD FR-3.11): `Cần kiểm lại`. Một đoạn ghi chỉ **tested locally** với dữ liệu giả và migration `speech_transcripts` chưa áp ở môi trường nào; đoạn khác ghi migration này đã áp lên development ngày 2026-11-08 (`20261108051456`). Chưa có luồng nào chạy với người học thật.
- Giảm chi phí Live (nén ngữ cảnh 6000 → 3000 token, im lặng 1000 ms): **tested locally**; Vertex nhận cấu hình nén trên một kết nối thật.

Tiến bộ và Home:
- Module `progress` (`GET /learner/me/progress`: chuỗi ngày, heatmap 365 ngày, thẻ theo trạng thái FSRS, độ chính xác, điểm phát âm, ngữ pháp, vùng học, phút nói), trang Tiến bộ dạng biểu đồ, thẻ Home: **code written**, **tested locally**, đã deploy. Chưa **verified in a real environment**.
- Tổng hợp tiến bộ chuyển vào hàm SQL `v3.learner_progress_totals` (migration `20261116110000`, nhánh `perf/progress-sql`): API gọi một lần thay vì đọc từng trang tối đa 20.000 dòng nhật ký và 20.000 thẻ. **Code written**, **tested locally**; thân hàm chạy dạng SELECT chỉ đọc trên dev cho ra cùng số với cách cũ (một tài khoản có dữ liệu). Ngày 2026-11-16, với phê duyệt của chủ dự án: migration đã áp trên Supabase development (ledger `20261116155406`; chỉ `service_role` được gọi) và backend image `d98e438120ca` (commit `50893041`, đã gộp vào `main` qua PR #122) đã deploy, `rollout.py verify` đạt. Gọi service tiến bộ trong container API cho tài khoản có dữ liệu ra đúng số đã so; route trả 401 khi chưa đăng nhập (**verified in a real environment** ở mức máy chủ, chưa mở trang Tiến bộ bằng tài khoản người học).

Web chung:
- Giao diện tiếng Việt theo ngôn ngữ hỗ trợ (khoảng 800 chuỗi); bản dịch do agent viết, chỉ kiểm bằng test.
- Giao diện theo Claude Design (Home, thanh Tata, Watch, Agent): **code written** trên nhánh `codex/home-design`, chưa được chủ dự án duyệt thị giác.
- Bộ kiểm chụp ảnh responsive (nhánh `test/web-responsive-matrix`): **tested locally**, 510 ca (17 màn × 10 khổ × 3 trình duyệt), không cuộn ngang; còn 63 ghi chú nút hoặc ô nhập nằm dưới thanh Tata/điều hướng. Dữ liệu giả, chưa chạy trên Safari hay điện thoại thật, không nằm trong CI.
- Ngữ pháp trong phụ đề (FR-8.2), cảnh báo tiếng Trung chưa hiệu chuẩn, ngân hàng câu hỏi ngữ pháp (FR-8.3, 32 câu A1/HSK1 đã được chủ dự án duyệt 2026-10-30), đề xuất chủ đề sổ tay: đã gộp vào `main` và chạy trên development; **tested locally**. Lời giải thích AI thật và bước đề xuất chủ đề chỉ chạy với người học dùng thử một lần (2026-10-30).
- Giáo trình mọi bậc (en A2–C2, zh HSK2–HSK6, 345 điểm ngữ pháp, A1 thêm 5): **code written**, qua bộ nạp offline; chờ chủ dự án duyệt mẫu, chưa nạp ở đâu.
- Bỏ JAM (2026-11-11): đã gỡ khỏi web, Flutter và backend; bảng dữ liệu không đổi, dòng cũ `source = "jam"` còn trong DB.

Flutter (`deeplingo_app`): **đã bỏ khỏi kho** trong đợt thu gọn 2026-11-15 (nhánh `refactor/slim-backend`); bản cuối ở tag git `archive/flutter-app-20261115`. Trước khi bỏ, app từng **verified in a real environment** trên API development một lần (emulator Android, 2026-10-31).

## Chưa kiểm chứng

- Giọng người thật và chất lượng micro; không có thử echo khi video phát, không thử trên điện thoại; chất lượng điểm Azure trên giọng thật; việc model có theo thang gợi ý và gọi công cụ đúng lúc; thẻ Sound natural (chưa hiện trong lần thử); tool mới của agent chưa xác nhận trong thử giọng thật.
- Chưa có nghiên cứu với người học thật, chưa đo kết quả học hay hiệu chuẩn; bằng chứng dùng từ tiếng Trung dương tính, dùng độc lập (R4) trong phiên thật.
- Safari, điện thoại thật, iOS (đường micro và chọn tệp).
- Phủ sóng tiếng Trung chưa đáng tin (video HSK 1–2 được 88% cho người học HSK2).
- Tải lớn: tài khoản lớn (kể cả giới hạn đọc từ đã lưu/ứng viên), transcript dài, phân trang quá 20 dòng lịch sử.
- Pháp lý: giấy phép bộ từ (CEFR-J, NGSL, HSK 3.0), chia sẻ transcript YouTube, văn bản quyền riêng tư tiếng Việt chờ rà soát (PRD Q8); là cổng trước khi thương mại hóa hoặc công khai.
- Bản dịch tiếng Việt của giao diện chưa có người đọc tiếng Việt rà soát.
- Qualification AI đầy đủ vẫn bị chặn; các lần chạy thử có giới hạn không đủ cho mọi tính năng AI. Mọi ngân sách AI đã duyệt cho đến nay đã dùng hết.

## Vấn đề đã biết

- Giới hạn giọng nói (thời lượng phiên, bộ đếm giây được cấp, chống phát lại ticket) chạy trong bộ nhớ của tiến trình, mất khi khởi động lại.
- Sổ ghi chi tiêu AI: trong code ở commit này có sổ dùng AI (`backend/app/platform/llm/ledger.py`, bảng `v3.ai_usage_events`, bật bằng `AI_USAGE_LEDGER_ENABLED`, mặc định bật). Sổ chỉ ghi số token của các lời gọi model có cấu trúc (`openai_compatible.py`), không chặn chi tiêu và không ghi số giây Gemini Live. Chưa có sổ chi tiêu bền cho giọng nói. Bảng `v3.ai_usage_events` có trên development và đã có dữ liệu (kiểm bằng truy vấn chỉ đọc 2026-11-18).
- 63 ghi chú responsive (ở trên); chưa chạy trong CI.
- Beat/hàng đợi vùng học: 2 vùng `failed` và 4 vùng còn đang chạy hoặc chờ thử lại trên development.
- Đã bỏ khỏi code nhưng còn trong DB development cho tới khi áp migration nháp: bảng và hàm của engine phiên học cũ, cột `self_usage`, bảng `learner_quick_review_skips`.

## Cách chạy các kiểm tra chính

- Backend, từ `backend/` với `venv/` bật: `python -m pytest -q`; ranh giới kiến trúc: `python -m pytest -q tests/architecture` (import-linter, phải xanh). Test thường không cần khóa hay hạn mức AI thật.
- Web, từ `deeplingo_web/`: `npm run typecheck`, `npm test`, `npm run lint`, `npm run build`, `npm run audit:build`, `npm run check:bundle` (ngân sách 116 KiB gzip, chủ dự án duyệt 2026-11-10; mục vào bản release 115,0 KiB), `npm run test:e2e:deterministic` (API giả).
- Ảnh responsive: `npm run test:e2e:responsive` rồi `npm run report:responsive` (cần `npx playwright install webkit firefox` một lần).
- Deploy development: `rollout.py` (`verify` kiểm nguồn khớp byte) cho VM, `verify_public.py` cho web Hosting; cần phê duyệt của chủ dự án cho từng lần.

## Quyết định đang chờ chủ dự án

- Phạm vi và ngân sách thử giọng người thật (hoãn; cần ngân sách và danh sách tài khoản cho phép trước khi gọi dịch vụ trả phí).
- Folding modules 6 to 3 (giữ nguyên cách ghi gốc).
- Công nghệ UI cho web và app; ai chấm mẫu hiệu chuẩn.
- Cấp độ hợp chất tiếng Trung (đã chốt giữ nhãn phủ sóng kèm cảnh báo hiệu chuẩn, FR-1.4, Q1).
