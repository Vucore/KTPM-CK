# Đặc tả đặt vé

Thanh mua vé nhanh lọc các suất theo phim, phòng chiếu và ngày tại Việt Nam. Khi thay đổi bộ lọc, giao diện bỏ lựa chọn cũ ở các bước phụ thuộc. Nút **Chọn ghế** chỉ mở khi khách chọn một suất hợp lệ. Nút giờ chiếu dưới poster mở thẳng sơ đồ ghế của suất đó.

Khách chọn từ 1 đến 8 ghế khác nhau trong một suất tương lai. Booking lấy giá gốc và loại ghế từ Catalog, cộng 15.000 ₫ vào cuối tuần theo giờ Việt Nam và 20.000 ₫ cho ghế cao cấp. Đơn lưu giá đã chốt theo đơn vị đồng. Tên trên vé là tùy chọn.

Trạng thái ghế theo từng suất gồm `AVAILABLE` (có thể chọn), `HELD` (đang thuộc một đơn giữ ghế còn hạn) và `SOLD` (đã xác nhận bán). Nếu một ghế trong nhóm vừa bị giữ hoặc đã bán, toàn bộ yêu cầu bị từ chối với mã 409. Giao diện tải lại sơ đồ để khách chọn ghế khác.

| Trạng thái đơn | Điều kiện | Kết quả |
|---|---|---|
| `HELD` | Toàn bộ ghế yêu cầu có thể giữ | Tạo đơn và giữ tất cả ghế trong cùng transaction. Hạn chót là thời điểm sớm hơn giữa TTL và giờ chiếu. |
| `CONFIRMED` | Booking xử lý giao dịch thành công trước hạn và vẫn sở hữu đủ ghế | Chuyển ghế thành `SOLD`, tạo một vé mỗi ghế trong cùng transaction. |
| `EXPIRED` | Đến hạn mà đơn chưa được xác nhận | Giải phóng các ghế vẫn thuộc đơn, cho phép khách khác giữ. Giao dịch thành công xử lý sau hạn được hoàn tiền. |

Booking khóa các hàng ghế theo thứ tự nhãn trước khi quyết định. Ghế giữ quá hạn có thể cấp lại kể cả khi tác vụ dọn chưa chạy. Tác vụ hết hạn chỉ trả các ghế còn thuộc đơn cũ. Booking dùng đồng hồ PostgreSQL để xác định hạn. Ghế đã bán khóa theo cặp suất và nhãn ghế.

Thời gian giữ mặc định là 300 giây, có thể cấu hình bằng `HOLD_SECONDS` từ 1 đến 3600. Giao diện tính thời gian còn lại dựa trên `expires_at` và `server_now` do Booking trả về.

Thanh toán có thể đi qua `PENDING → PROCESSING → SUCCEEDED` hoặc `DECLINED`. Khách có thể thử lại từ `DECLINED` khi còn giữ ghế. Nếu cần hoàn tiền, trạng thái chuyển `SUCCEEDED → REFUNDED`. Gộp yêu cầu lặp theo khóa idempotency và sự kiện lặp theo mã khoản thanh toán.

## Vé điện tử và QR

- Khi Payment trả `SUCCEEDED`, giao diện tiếp tục đọc trạng thái đơn. Booking chỉ cấp vé sau khi xác nhận `CONFIRMED`. Mỗi ghế trong đơn có một mã vé UUID riêng.
- QR được trả dưới dạng SVG và mã hóa chuỗi UUID của vé. Quét QR thu được mã dạng chữ để nhập vào **Tra cứu bằng mã**. API tra cứu trả thông tin phim, phòng, giờ chiếu và ghế của vé tương ứng. Đọc vé hoặc hình QR giữ nguyên trạng thái của hệ thống.
- Đường dẫn `/?booking=<mã đơn>` mở lại đơn kèm toàn bộ vé đã cấp theo quyền truy cập của đơn. Đường dẫn `/?view=tickets&ticket=<mã vé>` mở đúng một vé. [Quyền truy cập](accounts.md), [hợp đồng API](contracts.md).
