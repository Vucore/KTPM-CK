# Kịch bản demo

Dùng suất còn ghế trong giao diện. Trạng thái ghế cập nhật khi có tín hiệu bán vé và được tải lại định kỳ.

| Tình huống | Thao tác | Kết quả |
|---|---|---|
| Thành công | Chọn hai ghế, giữ ghế, thanh toán thành công với độ trễ 0. | Đơn xác nhận và hiện hai vé QR. Tải lại trang vẫn giữ nguyên mã vé. |
| Tranh cùng ghế | Mở hai tab, chọn cùng ghế và giữ gần như đồng thời. | Một tab nhận đơn. Tab kia nhận 409 hoặc thấy ghế đổi trạng thái trước khi có thể gửi. |
| Giữ cả nhóm | Gọi checkout qua Swagger với một ghế trống và một ghế đã giữ, dùng khóa mới. | Nhận 409. Ghế còn trống vẫn đặt được. |
| Từ chối | Chọn kết quả bị từ chối, sau đó thử lại với thành công trong hạn. | Phiên hiển thị thất bại rồi nhận vé sau lượt thành công. |
| Thành công trễ | Đặt `HOLD_SECONDS=15` rồi khởi động lại service. Giữ ghế và gửi thanh toán thành công với độ trễ 20 giây. Sau khi đơn hết hạn, thử giữ ghế bằng tab khác. | Đơn đầu nhận trạng thái hoàn tiền và không có vé. Ghế thuộc lượt giữ mới. |
| Broker dừng | Với TTL mặc định, giữ ghế, chạy `docker compose stop rabbitmq`, rồi gửi thanh toán thành công. Sau đó chạy `docker compose start rabbitmq`. | Payment lưu thành công khi broker dừng. Khi broker chạy lại, Booking cấp vé nếu còn hạn hoặc yêu cầu hoàn tiền nếu đã hết hạn. |
