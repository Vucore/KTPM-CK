# Đặc tả đặt vé

Khách chọn từ 1 đến 8 ghế khác nhau trong một suất tương lai. Booking lấy giá gốc và loại ghế từ Catalog, cộng 15.000 ₫ vào cuối tuần theo giờ Việt Nam và 20.000 ₫ cho ghế cao cấp. Đơn lưu giá đã chốt theo đơn vị đồng. Tên trên vé là tùy chọn.

| Trạng thái đơn | Điều kiện | Kết quả |
|---|---|---|
| `HELD` | Toàn bộ ghế yêu cầu có thể giữ | Tạo đơn và giữ tất cả ghế trong cùng transaction. Hạn chót là thời điểm sớm hơn giữa TTL và giờ chiếu. |
| `CONFIRMED` | Booking xử lý giao dịch thành công trước hạn và vẫn sở hữu đủ ghế | Chuyển ghế thành `SOLD`, tạo một vé mỗi ghế trong cùng transaction. |
| `EXPIRED` | Đến hạn mà đơn chưa được xác nhận | Giải phóng các ghế vẫn thuộc đơn, cho phép khách khác giữ. Giao dịch thành công xử lý sau hạn được hoàn tiền. |

Booking khóa các hàng ghế theo thứ tự nhãn trước khi quyết định. Ghế giữ quá hạn có thể cấp lại kể cả khi tác vụ dọn chưa chạy. Tác vụ hết hạn chỉ trả các ghế còn thuộc đơn cũ. Booking dùng đồng hồ PostgreSQL để xác định hạn. Ghế đã bán khóa theo cặp suất và nhãn ghế.

Thanh toán có thể đi qua `PENDING → PROCESSING → SUCCEEDED` hoặc `DECLINED`. Khách có thể thử lại từ `DECLINED` khi còn giữ ghế. Nếu cần hoàn tiền, trạng thái chuyển `SUCCEEDED → REFUNDED`. Gộp yêu cầu lặp theo khóa idempotency và sự kiện lặp theo mã khoản thanh toán.
