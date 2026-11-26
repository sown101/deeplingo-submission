# Chính sách quyền riêng tư DeepLingo (bản nháp)

Trạng thái: BẢN NHÁP, cập nhật 2026-11-07 (bản ghi lời nói có đồng ý riêng, FR-3.11), chưa được rà soát pháp lý. Áp dụng cho bản thử nghiệm
(development). Trước khi mở cho người dùng rộng rãi, cần người am hiểu pháp luật về bảo vệ
dữ liệu cá nhân (Nghị định 13/2023/NĐ-CP và luật hiện hành) xem lại. Chỗ `[email liên hệ]`
cần được chủ dự án điền.

Văn bản này là nguồn gốc của trang "Quyền riêng tư" trên web (`/privacy`) và trong ứng dụng.
Khi sửa ở đây, cập nhật cả hai nơi.

## 1. Chúng tôi thu thập gì

- **Tài khoản:** email và mật khẩu (do Supabase Auth quản lý; DeepLingo không đọc được mật
  khẩu), tên hiển thị, múi giờ.
- **Ngôn ngữ học:** ngôn ngữ bạn học, ngôn ngữ giải thích, mục tiêu.
- **Thư viện:** các video YouTube bạn thêm vào để học.
- **Kết quả học:** câu trả lời của bạn trong bài tập, điểm và nhận xét, mức độ nắm từng từ,
  kỹ năng, lịch ôn tập.
- **Từ đã lưu và nhóm từ** do bạn tạo.
- **Nhật ký luyện của từng video:** câu đã nghe chép (số từ đúng và vài từ bị thiếu, không lưu nguyên câu bạn gõ), câu đã nói theo (không lưu điểm hay ghi âm), từ bạn đã tra, câu hỏi hiểu đoạn video bạn đã trả lời (đúng hay sai), đoạn bạn chọn học, số lượt nói với bạn đồng hành (không lưu lời nói) và bản tóm tắt cuối mỗi buổi. Bạn đồng hành dùng để nối tiếp buổi học.
- **Điều agent biết về bạn** (chỉ khi bạn đồng ý xử lý giọng nói): các **tín hiệu có cấu trúc**, mỗi tín
  hiệu chỉ là một nhãn trong danh sách cố định: nhóm chủ đề bạn quan tâm (ví dụ du lịch, công nghệ),
  mục tiêu học bạn đã nói (ví dụ thi cử), loại lỗi ngữ pháp hay gặp (ví dụ chia thì quá khứ),
  tốc độ nói (chậm, vừa, nhanh) và độ dài lượt nói (ngắn, vừa, dài). **Không lưu** tên người, địa điểm,
  nơi làm việc, quan hệ, sức khỏe, câu bạn đã nói hay trích dẫn.
- **Đồng ý xử lý giọng nói:** thời điểm bạn đồng ý hoặc rút lại.
- **Bản ghi lời nói** (chỉ khi bạn bật đồng ý riêng "lưu bản ghi để hiệu chuẩn và xem lại", mặc định tắt, và
  đồng ý xử lý giọng nói cũng đang bật): với mỗi lượt bạn nói trong trò chuyện giọng nói với agent, chữ của lời bạn
  nói (bản chép của Google Gemini và, khi có chấm phát âm, bản nhận dạng của Microsoft Azure), câu của agent ngay
  trước đó, điểm phát âm theo từng từ, ngôn ngữ, chủ đề hoặc video, mức gợi ý bạn đã dùng, và các lỗi ngữ pháp
  agent đã sửa kèm câu gốc. **Không lưu âm thanh.** Dùng để hiệu chuẩn trình độ nói và để bạn xem lại lỗi của
  mình, và **agent được đọc lại** một số lượt gần nhất của chính bạn (tối đa 8 lượt, có giới hạn độ dài) để nhớ
  các buổi trước khi trò chuyện, chỉ khi cả hai đồng ý đang bật. Không dùng để chấm điểm, đổi bậc từ hay lịch ôn,
  và không ghi vào nhật ký hệ thống. Thời điểm bạn bật
  hoặc tắt đồng ý này cũng được lưu.
- **Điểm phát âm** (khi bạn đã đồng ý xử lý giọng nói): điểm trung bình mỗi lần luyện nói và các từ phát âm yếu, để hiện ở mục Tiến bộ. Không có âm thanh hay câu bạn đã nói; tự xóa sau 12 tháng.
- **Các buổi nói:** thời điểm, ngôn ngữ, loại (trò chuyện, nói theo, nói 1 phút) và số giây, để tính chuỗi
  ngày luyện. Không có nội dung.

## 2. Chúng tôi không lưu gì

- **Không lưu ghi âm giọng nói.** Âm thanh khi bạn luyện nói (shadowing, nói 1 phút, trò chuyện
  với agent) chỉ được giữ trong bộ nhớ trong lúc xử lý (với agent: từng lượt nói, tối đa 30 giây) rồi bỏ đi.
  Khi bạn trò chuyện với agent, âm thanh từng lượt nói **được gửi cho Microsoft Azure Speech để chấm phát âm**; việc
  này nằm trong sự đồng ý xử lý giọng nói của bạn.
- **Không lưu nội dung cuộc trò chuyện** với agent, trừ khi bạn bật đồng ý lưu bản ghi (mục 1). Nếu không bật,
  lời bạn nói chỉ được giữ tạm trong kho riêng tối đa 15 phút để kiểm tra từ bạn đã dùng, rồi xóa; chỉ các tín
  hiệu ở mục 1 được giữ.
- Không bán dữ liệu, không dùng cho quảng cáo.

## 3. Dữ liệu được gửi đến đâu

Để ứng dụng hoạt động, một phần dữ liệu được xử lý bởi các nhà cung cấp sau:

| Nhà cung cấp | Mục đích | Dữ liệu |
| --- | --- | --- |
| Supabase | Đăng nhập, lưu trữ dữ liệu | Toàn bộ dữ liệu ở mục 1 |
| Google Cloud | Máy chủ ứng dụng | Dữ liệu đi qua máy chủ khi bạn dùng app |
| Google Gemini (AI) | Chép lời video, giải thích nghĩa, chấm câu trả lời, bạn đồng hành | Nội dung video, câu trả lời và lời nói của bạn (dạng chữ hoặc âm thanh) trong lúc xử lý; khi bạn bật lưu bản ghi, một số lượt nói gần nhất đã lưu |
| Microsoft Azure Speech | Đọc câu trả lời của bạn đồng hành, chấm phát âm | Câu cần đọc; âm thanh khi chấm phát âm |
| Firebase Hosting | Phục vụ trang web | Không lưu dữ liệu học của bạn |

Việc các nhà cung cấp lưu giữ dữ liệu trong quá trình xử lý tuân theo điều khoản của họ.

## 4. Lưu trong bao lâu

- Tín hiệu cá nhân hóa: giữ đến khi bạn xoá chúng hoặc xoá tài khoản.
- Bản ghi lời nói: tự xoá sau **12 tháng** kể từ lượt nói, hoặc sớm hơn khi bạn xoá chúng hoặc xoá tài khoản. Tắt
  đồng ý thì không lưu bản ghi mới; bản ghi đã lưu vẫn giữ cho tới khi bạn xoá hoặc hết 12 tháng.
- Bộ nhớ ghi chú dạng chữ của bạn đồng hành trước đây đã **ngừng dùng**; các ghi chú cũ sẽ bị xoá khi bảng cũ được gỡ.
- Nhật ký luyện và nhật ký học tập (kết quả bài tập, từ đã lưu và tra, lượt nói, yêu cầu học agent giao): giữ đến khi bạn xoá chúng hoặc xoá tài khoản; nhật ký luyện theo video còn bị xoá khi bạn xoá video khỏi thư viện. Không có âm thanh trong đó.
- Từ bạn đã tra (để đưa vào Ôn nhanh mà không cần lưu): tự xoá sau **90 ngày** kể từ lần tra gần nhất. Từ bạn bấm "Bỏ mục này" được giữ tới khi bạn thêm lại trong Từ của tôi.
- Dữ liệu khác: giữ đến khi bạn yêu cầu xoá tài khoản.

## 5. Quyền của bạn

- **Xem và tải dữ liệu:** dùng nút "Tải dữ liệu của tôi" trên web (file JSON), hoặc "Sao chép
  dữ liệu của tôi" trong ứng dụng.
- **Đồng ý xử lý giọng nói:** đồng ý một lần, bật hoặc tắt bất cứ lúc nào ở trang Profile. Khi tắt, agent
  không xử lý giọng nói của bạn, không phân tích và không chấm phát âm.
- **Điều agent biết về bạn:** xem và xoá từng tín hiệu hoặc xoá hết tại trang Profile.
- **Bản ghi lời nói:** bật hoặc tắt đồng ý riêng, xem, xoá từng bản ghi hoặc xoá hết tại trang Profile (web). Bản
  ghi có trong file "Tải dữ liệu của tôi".
- **Xoá tài khoản:** thẻ "Delete my account" ở trang Profile (gõ DELETE để xác nhận) xoá tài khoản và mọi dữ
  liệu riêng của bạn ngay. Video, transcript và từ điển dùng chung không phải dữ liệu riêng nên không bị xoá.
- **Sửa dữ liệu hoặc rút lại các sự đồng ý khác:** gửi yêu cầu tới `[email liên hệ]` từ email bạn dùng để
  đăng nhập. Chúng tôi phản hồi trong thời hạn pháp luật quy định.

## 6. Nguồn dữ liệu từ điển

Nghĩa của từ lấy từ Wiktionary (CC BY-SA 4.0) và CC-CEDICT (CC BY-SA 4.0); danh sách từ dùng
CEFR-J, Octanove và NGSL. Ghi nguồn hiển thị cạnh mỗi nghĩa.

## 7. Thay đổi

Khi chính sách thay đổi, chúng tôi cập nhật ngày ở đầu văn bản và thông báo trong ứng dụng
nếu thay đổi ảnh hưởng đến dữ liệu của bạn.
