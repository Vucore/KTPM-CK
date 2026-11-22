# Kế hoạch thiết kế lại giao diện Chọn Suất

## Mục tiêu

Khách mở trang chủ có thể trả lời ngay ba câu hỏi: có phim gì, chiếu khi nào và còn ghế nào. Luồng chính gồm bốn bước **chọn suất → chọn ghế → thanh toán giả lập → nhận vé QR**. Các bước dùng dữ liệu thật từ Catalog, Booking và Payment của đồ án.

## Bài học từ Galaxy Cinema

Galaxy Cinema đặt danh mục phim, lịch chiếu và lối mua vé nhanh ngay trên trang chủ. Khách có thể bắt đầu từ phim mình muốn xem hoặc từ thời gian mình rảnh. Chọn Suất hiện có hai phim mẫu và một phòng, nên lối chọn nhanh chỉ cần hai trường **Phim** và **Suất chiếu**. Tên phòng xuất hiện ngay trong lựa chọn suất. [Trang tham khảo Galaxy Cinema](https://www.galaxycine.vn/)

Hướng mỹ thuật đề xuất cho Chọn Suất là nền trắng ngà ở phần duyệt lịch, xanh mực cho tiêu đề và màu cam đất cho hành động đặt vé. Khu chọn ghế dùng nền tối để gợi không gian phòng chiếu. Tên phim và hình ảnh riêng của hai phim mẫu giữ vai trò chính. Mọi giờ chiếu, giá và trạng thái đều lấy từ hệ thống.

## Thiết kế theo màn hình

| Màn hình | Bố cục và hành vi dự kiến | Tiêu chí nghiệm thu |
|---|---|---|
| Trang chủ và lịch chiếu | Đầu trang giới thiệu một phim có suất sắp tới. Ngay bên dưới là thanh đặt nhanh và danh sách phim có ảnh, thể loại, thời lượng, ngày giờ cụ thể. Các suất của cùng phim được nhóm lại. | Từ trang chủ, khách có thể bấm trực tiếp giờ chiếu để mở đúng sơ đồ ghế. Đổi phim trong thanh đặt nhanh sẽ cập nhật các suất tương ứng. Khi hết suất, trang hiển thị trạng thái trống. |
| Chọn ghế | Hiện phim, ngày giờ, phòng, vị trí màn hình và sơ đồ hàng ghế. Bảng tóm tắt liệt kê ghế đã chọn và nút giữ ghế. Trên điện thoại, hành động chính nằm ngay sau sơ đồ và luôn trong tầm thao tác. | Phân biệt được ghế trống, cao cấp, đang chọn và hết chỗ bằng cả màu lẫn ký hiệu hoặc nhãn. Khi gặp HTTP 409, khách thấy ghế vừa mất và có thể chọn lại. |
| Thanh toán | Đặt tên phim, ghế, tổng tiền do Booking trả về và thời gian giữ còn lại cùng một nhóm. Bên cạnh là khối **Thanh toán giả lập**, với kết quả và độ trễ đã có trong hệ thống. | Khi gửi yêu cầu, nút chuyển sang trạng thái chờ. Thanh toán bị từ chối cho phép thử lại trong hạn. Đơn hết hạn và giao dịch đã hoàn tiền có thông báo riêng. |
| Vé điện tử | Mỗi ghế có một vé, hiển thị tên phim, phòng, giờ chiếu, số ghế và QR trên nền trắng. Đặt hành động trở lại lịch chiếu bên dưới vé. | Khách có thể phân biệt hai vé trong cùng đơn, quét từng QR trên điện thoại và mở lại đường dẫn đơn để xem đúng các vé đã cấp. |

## Thứ tự thực hiện sau khi duyệt

1. **Chốt bố cục.** Vẽ wireframe desktop và mobile cho bốn màn hình. Dùng dữ liệu hai phim mẫu để kiểm tra độ dài tiêu đề, cách nhóm suất và vị trí nút chính.
2. **Chuẩn bị hình ảnh và quy tắc hiển thị.** Tạo hình riêng cho *Sài Gòn Sau Mưa* và *Quỹ Đạo Cuối*, chọn kiểu chữ hỗ trợ tiếng Việt, quy định màu và trạng thái cho nút, ghế, vé. Có ảnh thay thế cho phim mới chưa có hình.
3. **Triển khai trang chủ và chọn ghế.** Sửa cấu trúc trong `cinema/web/index.html`, phong cách trong `cinema/web/style.css` và cách trình bày dữ liệu trong `cinema/web/app.js`. Kiểm tra cả hai đường vào sơ đồ ghế từ danh sách phim và thanh đặt nhanh.
4. **Triển khai thanh toán và vé.** Dùng các endpoint hiện có, đồng hồ từ server, khóa chống gửi lặp và URL truy xuất đơn. Kiểm tra thao tác tải lại trang trong lúc chờ kết quả.
5. **Nghiệm thu.** Chạy trọn luồng ở chiều rộng 360, 768 và 1440 px. Kiểm tra bàn phím, trạng thái focus, chữ tiếng Việt, khả năng quét QR và tràn ngang. Chạy lại các tình huống thanh toán thành công, từ chối, hết hạn, hoàn tiền và hai khách tranh ghế theo [kịch bản demo](demo.md).

**Điểm duyệt trước khi code:** hướng màu sắc, bố cục trang chủ và vị trí thanh đặt nhanh. Phạm vi dự kiến tập trung vào frontend hiện có, với Supabase và các microservice tiếp tục cung cấp dữ liệu qua API.
