import { Link, useNavigate } from "react-router-dom";
import { T, useT } from "../../i18n/i18n";
import { Icon } from "../../design/Icon";

// Mirrors docs/product/PRIVACY_NOTICE.md (draft). Update both together.
const PROVIDERS: [string, string, string][] = [
  ["Supabase", "Đăng nhập, lưu trữ dữ liệu", "Toàn bộ dữ liệu ở mục 1"],
  ["Google Cloud", "Máy chủ ứng dụng", "Dữ liệu đi qua máy chủ khi bạn dùng app"],
  ["Google Gemini (AI)", "Chép lời video, giải thích nghĩa, chấm câu trả lời, bạn đồng hành",
    "Nội dung video, câu trả lời và lời nói của bạn trong lúc xử lý; khi bạn bật lưu bản ghi, một số lượt nói gần nhất đã lưu"],
  ["Microsoft Azure Speech", "Đọc câu trả lời của bạn đồng hành, chấm phát âm",
    "Câu cần đọc; âm thanh khi chấm phát âm"],
  ["Firebase Hosting", "Phục vụ trang web", "Không lưu dữ liệu học của bạn"],
];

export function PrivacyScreen() {
  const t = useT();
  const navigate = useNavigate();
  // Opened from sign-in or from Profile: go back there; a direct visit goes to the start page.
  const back = () => (window.history.length > 1 ? navigate(-1) : navigate("/"));
  return (
    <div className="page privacy-screen">
      <div className="page-head page-head--back">
        <button type="button" className="dl-icon-btn" onClick={back} aria-label={t("Back")} title={t("Back")}><Icon name="back" /></button>
        <h1><T>Quyền riêng tư</T></h1>
      </div>
      <p className="muted small"><T>Bản nháp cập nhật ngày 07/11/2026, áp dụng cho bản thử nghiệm.</T></p>

      <h2><T>1. Chúng tôi thu thập gì</T></h2>
      <ul>
        <li><strong><T>Tài khoản:</T></strong> <T>email và mật khẩu (Supabase quản lý; DeepLingo không đọc được mật khẩu), tên hiển thị, múi giờ.</T></li>
        <li><strong><T>Ngôn ngữ học:</T></strong> <T>ngôn ngữ bạn học, ngôn ngữ giải thích, mục tiêu.</T></li>
        <li><strong><T>Thư viện:</T></strong> <T>các video YouTube bạn thêm để học.</T></li>
        <li><strong><T>Kết quả học:</T></strong> <T>câu trả lời trong bài tập, điểm và nhận xét, mức độ nắm từng từ, kỹ năng, lịch ôn tập.</T></li>
        <li><strong><T>Từ đã lưu và nhóm từ</T></strong> <T>do bạn tạo.</T></li>
        <li><strong><T>Nhật ký luyện của từng video:</T></strong> <T>câu đã nghe chép (số từ đúng và vài từ bị thiếu, không lưu nguyên câu bạn gõ), câu đã nói theo (không lưu điểm hay ghi âm), từ bạn đã tra, câu hỏi hiểu đoạn video bạn đã trả lời (đúng hay sai), đoạn bạn chọn học, số lượt nói với bạn đồng hành (không lưu lời nói) và bản tóm tắt cuối mỗi buổi. Bạn đồng hành dùng để nối tiếp buổi học.</T></li>
        <li><strong><T>Điều agent biết về bạn</T></strong> <T>(chỉ khi bạn đồng ý xử lý giọng nói): các tín hiệu có cấu trúc, mỗi tín hiệu chỉ là một nhãn trong danh sách cố định: nhóm chủ đề bạn quan tâm, mục tiêu học bạn đã nói, loại lỗi ngữ pháp hay gặp, tốc độ nói và độ dài lượt nói. Không lưu tên người, địa điểm, nơi làm việc, quan hệ, sức khỏe, câu bạn đã nói hay trích dẫn.</T></li>
        <li><strong><T>Đồng ý xử lý giọng nói:</T></strong> <T>thời điểm bạn đồng ý hoặc rút lại.</T></li>
        <li><strong><T>Bản ghi lời nói</T></strong> <T>(chỉ khi bạn bật đồng ý riêng "lưu bản ghi để hiệu chuẩn và xem lại", mặc định tắt, và đồng ý xử lý giọng nói cũng đang bật): với mỗi lượt bạn nói trong trò chuyện giọng nói với agent, chữ của lời bạn nói (bản chép của Google Gemini và, khi có chấm phát âm, bản nhận dạng của Microsoft Azure), câu của agent ngay trước đó, điểm phát âm theo từng từ, ngôn ngữ, chủ đề hoặc video, mức gợi ý bạn đã dùng, và các lỗi ngữ pháp agent đã sửa kèm câu gốc. Không lưu âm thanh. Dùng để hiệu chuẩn trình độ nói, để bạn xem lại lỗi, và agent được đọc lại một số lượt gần nhất của chính bạn (tối đa 8 lượt, có giới hạn độ dài) để nhớ các buổi trước khi trò chuyện, chỉ khi cả hai đồng ý đang bật. Không dùng để chấm điểm, đổi bậc từ hay lịch ôn, và không ghi vào nhật ký hệ thống.</T></li>
        <li><strong><T>Các buổi nói:</T></strong> <T>thời điểm, ngôn ngữ, loại và số giây, để tính chuỗi ngày luyện. Không có nội dung.</T></li>
      </ul>

      <h2><T>2. Chúng tôi không lưu gì</T></h2>
      <ul>
        <li><strong><T>Không lưu ghi âm giọng nói.</T></strong> <T>Âm thanh khi luyện nói chỉ được giữ trong bộ nhớ lúc xử lý (với agent: từng lượt nói, tối đa 30 giây) rồi bỏ đi. Khi trò chuyện với agent, âm thanh từng lượt nói được gửi cho Microsoft Azure Speech để chấm phát âm; việc này nằm trong sự đồng ý xử lý giọng nói của bạn.</T></li>
        <li><strong><T>Không lưu nội dung cuộc trò chuyện</T></strong> <T>với agent, trừ khi bạn bật đồng ý lưu bản ghi (mục 1). Nếu không bật, lời bạn nói chỉ được giữ tạm tối đa 15 phút để kiểm tra từ bạn đã dùng, rồi xóa; chỉ các tín hiệu ở mục 1 được giữ.</T></li>
        <li><T>Không bán dữ liệu, không dùng cho quảng cáo.</T></li>
      </ul>

      <h2><T>3. Dữ liệu được gửi đến đâu</T></h2>
      <div className="table-scroll">
        <table>
          <thead><tr><th><T>Nhà cung cấp</T></th><th><T>Mục đích</T></th><th><T>Dữ liệu</T></th></tr></thead>
          <tbody>
            {PROVIDERS.map(([name, purpose, data]) => (
              <tr key={name}><td>{name}</td><td>{purpose}</td><td>{data}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2><T>4. Lưu trong bao lâu</T></h2>
      <ul>
        <li><T>Tín hiệu cá nhân hóa: giữ đến khi bạn xoá chúng hoặc xoá tài khoản. Bộ nhớ ghi chú dạng chữ của bạn đồng hành trước đây đã ngừng dùng; các ghi chú cũ sẽ bị xoá khi bảng cũ được gỡ.</T></li>
        <li><T>Bản ghi lời nói: tự xoá sau</T> <strong><T>12 tháng</T></strong> <T>kể từ lượt nói, hoặc sớm hơn khi bạn xoá chúng hoặc xoá tài khoản. Tắt đồng ý thì không lưu bản ghi mới; bản ghi đã lưu vẫn giữ cho tới khi bạn xoá hoặc hết 12 tháng.</T></li>
        <li><T>Nhật ký luyện: tự xoá sau</T> <strong><T>90 ngày</T></strong><T>, hoặc khi bạn xoá video khỏi thư viện.</T></li>
        <li><T>Từ bạn đã tra (để đưa vào Ôn nhanh mà không cần lưu): tự xoá sau</T> <strong><T>90 ngày</T></strong> <T>kể từ lần tra gần nhất. Từ bạn bấm "Bỏ mục này" được giữ tới khi bạn thêm lại trong Từ của tôi.</T></li>
        <li><T>Dữ liệu khác: giữ đến khi bạn yêu cầu xoá tài khoản.</T></li>
      </ul>

      <h2><T>5. Quyền của bạn</T></h2>
      <ul>
        <li><strong><T>Xem và tải dữ liệu:</T></strong> <T>nút "Tải dữ liệu của tôi" ở trang chủ (file JSON).</T></li>
        <li><strong><T>Đồng ý xử lý giọng nói:</T></strong> <T>đồng ý một lần, bật hoặc tắt bất cứ lúc nào tại</T> <Link to="/account"><T>trang Profile</T></Link><T>. Khi tắt, agent không xử lý giọng nói của bạn, không phân tích và không chấm phát âm.</T></li>
        <li><strong><T>Điều agent biết về bạn:</T></strong> <T>xem và xoá từng tín hiệu hoặc xoá hết tại trang Profile.</T></li>
        <li><strong><T>Bản ghi lời nói:</T></strong> <T>bật hoặc tắt đồng ý riêng, xem, xoá từng bản ghi hoặc xoá hết tại trang Profile. Bản ghi có trong file "Tải dữ liệu của tôi".</T></li>
        <li><strong><T>Xoá tài khoản:</T></strong> <T>thẻ "Delete my account" ở trang Profile (gõ DELETE để xác nhận) xoá tài khoản và mọi dữ liệu riêng của bạn ngay. Video, transcript và từ điển dùng chung không bị xoá.</T></li>
        <li><strong><T>Sửa dữ liệu hoặc rút lại các sự đồng ý khác:</T></strong> <T>gửi yêu cầu tới</T> <code>[email liên hệ]</code> <T>từ email bạn dùng để đăng nhập.</T></li>
      </ul>

      <h2><T>6. Nguồn từ điển</T></h2>
      <p><T>Nghĩa của từ lấy từ Wiktionary (CC BY-SA 4.0) và CC-CEDICT (CC BY-SA 4.0); danh sách từ dùng CEFR-J, Octanove và NGSL.</T></p>

      <h2><T>7. Thay đổi</T></h2>
      <p><T>Khi chính sách thay đổi, chúng tôi cập nhật ngày ở đầu trang và thông báo trong ứng dụng nếu thay đổi ảnh hưởng đến dữ liệu của bạn.</T></p>
    </div>
  );
}
