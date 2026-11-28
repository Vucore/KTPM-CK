# Đặc tả tài khoản và lịch sử vé

## Tạo và sử dụng tài khoản

- Tên đăng nhập dài 3–32 ký tự, gồm chữ không dấu, số, dấu chấm, gạch dưới hoặc gạch ngang. Tên được chuẩn hóa về chữ thường. Mật khẩu khi đăng ký dài 15–128 ký tự và có thể chứa khoảng trắng.
- Đăng ký thành công mở một phiên đăng nhập. Khi đăng nhập trên thiết bị khác, cùng tài khoản thấy các đơn đã lưu. Đăng xuất thu hồi phiên hiện tại. Phiên hết hạn sau 30 ngày.
- Mật khẩu được băm bằng Argon2id. Booking tạo mã phiên ngẫu nhiên, lưu bản băm trong Supabase và gửi mã gốc qua cookie `HttpOnly`, `SameSite=Lax`. Cookie có `Secure` khi chạy qua HTTPS.
- Các lượt đăng ký và đăng nhập bị giới hạn theo địa chỉ nguồn và theo cặp tên đăng nhập–địa chỉ nguồn. Bộ đếm dùng chung qua PostgreSQL. Khi vượt ngưỡng trong cửa sổ 10 phút, API trả 429 và `Retry-After`.

## Ai được xem và lưu đơn

| Trường hợp | Hành vi |
|---|---|
| Đặt khi đã đăng nhập | Đơn thuộc tài khoản và tự hiện trong **Vé của tôi**. API đơn và thanh toán chỉ cho tài khoản đã đặt mở bằng mã đơn. |
| Đặt với vai trò khách | Đơn tự hiện trong lịch sử của trình duyệt đang dùng và được gắn với `hold_owner` của trình duyệt đó để chống truy cập trái phép (IDOR). Nếu khách đăng nhập ngay trên cùng trình duyệt, phiên đó vẫn giữ quyền thao tác tiếp với đơn vừa tạo. |
| Đơn khách cũ không có `hold_owner` | Mở bằng mã đơn hoặc đường dẫn cũ `/?booking=<mã đơn>`, rồi chọn **Lưu vào Vé của tôi** để thêm vào danh sách hiện tại. |
| Tra cứu bằng mã vé | Mở vé điện tử của đúng một ghế. Chỉ chủ sở hữu đơn (tài khoản hoặc trình duyệt đặt vé) và nhân viên `STAFF`/`ADMIN` được phép tra cứu vé và lấy QR. |
| Bỏ lưu một đơn | Bỏ liên kết khỏi lịch sử của tài khoản hoặc trình duyệt hiện tại. Đơn và các vé vẫn tồn tại. |

Khi chưa đăng nhập, Booking dùng cookie `chon_suat_browser` có hạn một năm để xác định lịch sử. Khi đã đăng nhập, Booking dùng `chon_suat_session` để xác định tài khoản. Việc đăng nhập chuyển lịch sử đang hiển thị sang tài khoản. Nếu muốn thêm một đơn khách, mở đơn bằng mã rồi bấm **Lưu vào Vé của tôi**. Thao tác này tạo liên kết lịch sử và giữ quyền truy cập gốc của đơn khách.

Đơn khách mới luôn gắn `hold_owner` với trình duyệt đặt vé nên trình duyệt hoặc tài khoản khác không thể xem, lưu, hủy hay đọc vé của đơn đó (trả `404`). Nếu khách đăng nhập trên chính trình duyệt vừa đặt, hệ thống vẫn nhận diện `browser_key` của trình duyệt đó để khách hoàn tất thanh toán hoặc hủy giữ ghế. Tra cứu vé QR theo mã chỉ cho phép chủ sở hữu đơn hoặc nhân viên `STAFF`/`ADMIN`.

Booking lưu liên kết lịch sử trong cùng transaction tạo đơn và giữ ghế. Supabase ràng buộc mỗi liên kết là duy nhất theo chủ lịch sử và mã đơn. Transaction giữ ghế vẫn khóa theo suất và nhãn ghế, áp dụng cho cả người dùng đăng nhập lẫn khách.

Đối chiếu đường dẫn trong [hợp đồng API](contracts.md) và cách thao tác trong [tài liệu giao diện](../docs/giao-dien.md).
