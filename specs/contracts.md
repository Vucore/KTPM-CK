# Hợp đồng API và sự kiện

Booking phục vụ trang web và API công khai của bản demo. Mã đơn và mã vé là UUID ngẫu nhiên. Payment nhận header nội bộ `X-Internal-Key`.

| REST | Đầu vào / kết quả |
|---|---|
| Catalog `GET /screenings`, `GET /screenings/{id}` | Danh sách suất tương lai hoặc chi tiết suất kèm ghế. Mỗi suất có `movie_id` để giao diện nhóm các suất của cùng phim. |
| Booking `GET /api/screenings`, `GET /api/screenings/{id}/seats` | Danh sách suất và sơ đồ ghế theo trạng thái. |
| Booking `GET /api/screenings/{id}/updates` | SSE báo thay đổi sau khi một đơn của suất được xác nhận. |
| Booking `POST /api/checkout` | Nhận suất, danh sách ghế và tên tùy chọn. Trả 201 cùng `booking` và `payment`. |
| Booking `GET /api/bookings/{id}`, `GET /api/bookings/{id}/payment` | Đọc đơn kèm vé hoặc phiên thanh toán. |
| Booking `POST /api/bookings/{id}/payment/simulate` | Nhận `outcome` và `delay_seconds` từ 0–120. Trả 202. |
| Booking `GET /api/tickets/{code}`, `GET /api/tickets/{code}/qr.svg` | Thông tin vé hoặc mã QR dạng SVG. |
| Payment `POST /payments`, `GET /payments/{booking_id}`, `POST /payments/{booking_id}/simulate` | API nội bộ dùng để tạo, truy vấn và giả lập thanh toán. Tạo phiên theo mã đơn và số tiền Booking cung cấp. |

Checkout và simulate yêu cầu `Idempotency-Key` là UUID. Gửi lại cùng khóa và dữ liệu sau timeout để tiếp tục đơn hoặc lượt thanh toán cũ. Dùng khóa mới cho thao tác mới. Ví dụ checkout `{"screening_id":"saigon-evening","seats":["A1","A2"],"customer_name":"Minh"}`. Ví dụ giả lập `{"outcome":"success","delay_seconds":0}`.

Mã lỗi chính gồm 404 khi đối tượng không tồn tại, 409 khi ghế bận hoặc yêu cầu xung đột, 422 khi đầu vào sai và 503 khi phụ thuộc tạm gián đoạn.

Hai sự kiện `payment.succeeded` và `payment.refund_requested` dùng chung payload `{"booking_id":"<uuid>","payment_id":"<uuid>","amount":180000}`. Outbox dùng cặp loại sự kiện và mã thanh toán để chống tạo trùng. RabbitMQ có thể giao lại sự kiện. Consumer xác nhận sau khi transaction commit và kiểm tra trạng thái trước khi cấp vé hoặc hoàn tiền.
