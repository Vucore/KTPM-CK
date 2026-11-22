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
| Đặt với vai trò khách | Đơn tự hiện trong lịch sử của trình duyệt đang dùng. Mã đơn mở lại toàn bộ đơn, kể cả khi đổi máy hoặc mất cookie trình duyệt. |
| Đơn khách từng đặt trước khi có lịch sử | Mở bằng mã đơn hoặc đường dẫn cũ `/?booking=<mã đơn>`, rồi chọn **Lưu vào Vé của tôi** để thêm vào danh sách hiện tại. |
| Tra cứu bằng mã vé | Mở vé điện tử của đúng một ghế. Mỗi mã vé mở được QR và thông tin suất của vé đó, nên chỉ chia sẻ với người cần dùng vé. |
| Bỏ lưu một đơn | Bỏ liên kết khỏi lịch sử của tài khoản hoặc trình duyệt hiện tại. Đơn và các vé vẫn tồn tại. |

Booking lưu liên kết lịch sử trong cùng transaction tạo đơn và giữ ghế. Supabase ràng buộc mỗi liên kết là duy nhất theo chủ lịch sử và mã đơn. Transaction giữ ghế vẫn khóa theo suất và nhãn ghế, áp dụng cho cả người dùng đăng nhập lẫn khách.

Đối chiếu đường dẫn trong [hợp đồng API](contracts.md) và cách thao tác trong [tài liệu giao diện](../docs/giao-dien.md).
