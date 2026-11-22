# Hợp đồng API và sự kiện

Booking phục vụ trang web và API công khai của bản demo. Mã đơn và mã vé là UUID ngẫu nhiên. Payment nhận header nội bộ `X-Internal-Key`.

| REST | Đầu vào / kết quả |
|---|---|
| Cả ba dịch vụ `GET /health` | Trả `{"status":"ok"}` nếu dịch vụ kết nối được PostgreSQL. |
| Catalog `GET /screenings`, `GET /screenings/{id}` | Danh sách suất tương lai hoặc chi tiết suất kèm ghế. Danh sách trả `movie_id` và `auditorium_id` để giao diện nhóm theo phim và phòng. |
| Booking `GET /api/screenings`, `GET /api/screenings/{id}/seats` | Danh sách suất và sơ đồ ghế theo trạng thái. |
| Booking `GET /api/screenings/{id}/updates` | SSE báo thay đổi sau khi một đơn của suất được xác nhận. |
| Booking `POST /api/checkout` | Nhận suất, danh sách ghế và tên tùy chọn. Trả 201 cùng `booking` và `payment`. |
| Booking `GET /api/bookings/{id}`, `GET /api/bookings/{id}/payment` | Đọc đơn kèm vé hoặc phiên thanh toán. Đơn trả `expires_at`, `server_now` và cờ `saved` cho phiên hiện tại. |
| Booking `POST /api/bookings/{id}/payment/simulate` | Nhận `outcome` là `success` hoặc `decline` và `delay_seconds` từ 0–120, mặc định 0. Mã 202 cho biết yêu cầu đã được nhận. Kết quả đọc từ API phiên thanh toán và API đơn. |
| Booking `GET /api/tickets/{code}` | Đọc một vé theo UUID. Phản hồi gồm `code`, `seat`, `movie_title`, `auditorium`, `starts_at`. |
| Booking `GET /api/tickets/{code}/qr.svg` | Trả `image/svg+xml`. Nội dung QR là chuỗi UUID của vé. |
| Payment `POST /payments`, `GET /payments/{booking_id}`, `POST /payments/{booking_id}/simulate` | API nội bộ dùng để tạo, truy vấn và giả lập thanh toán. Tạo phiên theo mã đơn và số tiền Booking cung cấp. |
| Booking `POST /api/auth/register`, `POST /api/auth/login` | Nhận JSON gồm `username` và `password`. Trả thông tin tài khoản và đặt cookie phiên. Sai thông tin đăng nhập trả 401. Tên trùng khi đăng ký trả 409. |
| Booking `GET /api/auth/session`, `POST /api/auth/logout` | Đọc `account` của phiên hiện tại hoặc `null`. Đăng xuất thu hồi phiên và trả 204. |
| Booking `GET /api/my-bookings` | Trả `scope` là `account` hoặc `browser` cùng danh sách `bookings` của phiên đó. |
| Booking `PUT /api/my-bookings/{id}`, `DELETE /api/my-bookings/{id}` | Lưu đơn được phép xem hoặc bỏ lưu khỏi danh sách hiện tại. Thành công trả 204. |

Quyền truy cập API đơn, thanh toán và lịch sử tuân theo [đặc tả tài khoản](accounts.md). Với đơn thuộc tài khoản, API trả 404 cho phiên không có quyền mở đơn. Với hai endpoint vé, mã hợp lệ cho phép tra cứu một vé, còn mã UUID không tồn tại trả 404.

Các yêu cầu ghi dữ liệu công khai kiểm tra header `Origin` nếu header này được gửi. API trả 403 nếu origin khác địa chỉ Booking. Các endpoint tài khoản có thể trả 429 với `Retry-After` khi vượt giới hạn lượt thử.

Checkout và simulate yêu cầu `Idempotency-Key` là UUID. Gửi lại cùng khóa và dữ liệu sau timeout để tiếp tục đơn hoặc lượt thanh toán cũ. Dùng khóa mới cho thao tác mới. Gửi lại cùng khóa với dữ liệu khác trả 409.

Ví dụ nội dung JSON của checkout với một suất có trong kết quả `GET /api/screenings`.

```json
{"screening_id":"saigon-evening","seats":["A1","A2"],"customer_name":"Minh"}
```

Ví dụ nội dung JSON của yêu cầu thanh toán giả lập.

```json
{"outcome":"success","delay_seconds":0}
```

Mã lỗi chính gồm 404 khi đối tượng không tồn tại, 409 khi ghế bận hoặc yêu cầu xung đột, 422 khi đầu vào sai và 503 khi phụ thuộc tạm gián đoạn.

Hai sự kiện `payment.succeeded` và `payment.refund_requested` dùng chung payload `{"booking_id":"<uuid>","payment_id":"<uuid>","amount":180000}`. Outbox dùng cặp loại sự kiện và mã thanh toán để chống tạo trùng. RabbitMQ có thể giao lại sự kiện. Consumer xác nhận sau khi transaction commit và kiểm tra trạng thái trước khi cấp vé hoặc hoàn tiền.
