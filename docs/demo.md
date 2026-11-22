# Kịch bản demo

Khởi động các dịch vụ theo [README](../README.md), mở trang Chọn Suất và chọn một suất tương lai còn ghế. Để thử hai người mua độc lập, dùng hai hồ sơ trình duyệt hoặc một cửa sổ thường và một cửa sổ riêng tư.

| Tình huống | Thao tác | Kết quả |
|---|---|---|
| Thành công | Chọn hai ghế, giữ ghế, thanh toán thành công với độ trễ 0. | Đơn xác nhận và hiện hai vé QR. Tải lại trang vẫn giữ nguyên mã vé. |
| Tranh cùng ghế | Từ hai trình duyệt, chọn cùng một ghế và giữ gần như đồng thời. | Một trình duyệt giữ được ghế. Trình duyệt kia nhận 409 hoặc thấy ghế đổi trạng thái trước khi có thể gửi. |
| Giữ cả nhóm | Gọi checkout qua Swagger với một ghế trống và một ghế đã giữ, dùng khóa mới. | Nhận 409. Ghế còn trống vẫn đặt được. |
| Từ chối | Chọn kết quả bị từ chối, sau đó thử lại với thành công trong hạn. | Phiên hiển thị thất bại rồi nhận vé sau lượt thành công. |
| Thành công trễ | Đặt `HOLD_SECONDS=15` rồi khởi động lại service. Giữ ghế và gửi thanh toán thành công với độ trễ 20 giây. Sau khi đơn hết hạn, thử giữ ghế bằng tab khác. | Đơn đầu nhận trạng thái hoàn tiền và không có vé. Ghế thuộc lượt giữ mới. |
| Broker dừng | Với TTL mặc định, giữ ghế, chạy `docker compose stop rabbitmq`, rồi gửi thanh toán thành công. Sau đó chạy `docker compose start rabbitmq`. | Payment lưu thành công khi broker dừng. Khi broker chạy lại, Booking cấp vé nếu còn hạn hoặc yêu cầu hoàn tiền nếu đã hết hạn. |
| Khách xem lại đơn | Đặt và thanh toán khi chưa đăng nhập. Sao chép mã đơn, mở hồ sơ trình duyệt khác rồi dán mã vào **Vé của tôi → Tra cứu bằng mã**. | Hồ sơ mới mở được đơn bằng mã. Bấm **Lưu vào Vé của tôi** để lưu vào lịch sử của phiên hiện tại. |
| Xem đơn theo tài khoản | Đăng nhập trước khi đặt rồi mở **Vé của tôi** trên trình duyệt khác bằng cùng tài khoản. Thử mở đường dẫn đơn sau khi đăng xuất. | Cùng tài khoản xem được lịch sử. Khi đăng xuất hoặc dùng tài khoản khác, API đơn trả 404. |
| Tra cứu bằng QR | Đặt hai ghế, thanh toán thành công, quét một trong hai mã QR bằng ứng dụng quét mã. Dán UUID vào **Tra cứu bằng mã**. | Giao diện hiển thị đúng một vé, gồm phim, phòng, suất và số ghế tương ứng. Thao tác có thể lặp lại để xem vé. |

Nếu đã đổi `HOLD_SECONDS` cho bài thử quá hạn, đưa giá trị về 300 và khởi động lại dịch vụ trước khi tiếp tục. Khi kết thúc, dừng các tiến trình đã mở cho phiên demo. [Cách dừng dịch vụ](../README.md#chạy-server-với-cấu-hình-đã-có).
