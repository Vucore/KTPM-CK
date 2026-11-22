# Giao diện Chọn Suất

## Luồng đặt vé

1. Trong **Mua vé nhanh**, chọn phim, phòng, ngày và suất rồi bấm **Chọn ghế**. Nếu phim chỉ có một phòng, giao diện chọn phòng đó. Bạn cũng có thể bấm thẳng giờ chiếu dưới poster.
2. Chọn tối đa 8 ghế và nhập tên trên vé nếu muốn. Khung bên phải trên laptop hiển thị phim, suất và danh sách ghế đã chọn. Sơ đồ cập nhật qua SSE và tải lại định kỳ. Nếu ghế vừa bị giữ hoặc bán, giao diện cập nhật trạng thái để khách chọn lại.
3. Kiểm tra tổng tiền và thời hạn giữ ghế trong phần tóm tắt đơn. Trong **Thanh toán giả lập**, chọn kết quả và độ trễ để chạy giao dịch. Nếu kết quả bị từ chối, khách có thể thử lại khi thời hạn còn hiệu lực.
4. Khi Booking xác nhận đơn, mỗi ghế có một vé và một QR riêng. Mở lại đường dẫn `/?booking=<mã đơn>` để xem đơn hoặc vé đã cấp.

## Xem lại vé

- Mở **Vé của tôi** trên thanh điều hướng để xem các đơn đã lưu theo phim, suất, ghế và trạng thái. **Xem vé** mở toàn bộ QR trong đơn. **Chi tiết vé** mở vé của một ghế trên giao diện.
- Chọn **Đăng nhập** hoặc **Tạo tài khoản** trước khi đặt để lưu lịch sử vào tài khoản. Để xem lại trên thiết bị khác, mở cùng website và đăng nhập bằng tài khoản đó.
- Đặt dưới dạng khách lưu lịch sử theo trình duyệt. Bạn vẫn xem được lịch sử khi đóng và mở lại trình duyệt nếu cookie còn. Khi đổi máy hoặc mất cookie, dán **Mã đơn** đã sao chép vào **Vé của tôi → Tra cứu bằng mã**.
- Nếu đơn thuộc tài khoản, hãy đăng nhập bằng tài khoản đã đặt trước khi tra cứu bằng mã đơn. Với đơn khách, bạn có thể mở lại bằng mã rồi bấm **Lưu vào Vé của tôi** để thêm vào lịch sử hiện tại. **Bỏ lưu** chỉ gỡ đơn khỏi danh sách.

## Quét mã QR

1. Mở **Vé của tôi → Xem vé** hoặc trang xác nhận đơn để thấy mã QR của từng ghế.
2. Quét QR bằng ứng dụng đọc mã và sao chép UUID mà ứng dụng trả về.
3. Dán UUID vào **Vé của tôi → Tra cứu bằng mã** để xem thông tin của ghế đó. **Chi tiết vé** mở cùng thông tin trực tiếp trên website.

Một QR đại diện cho một vé. Tính năng hiện tại dùng để tra cứu vé điện tử. Quét mã giữ nguyên trạng thái vé và đơn. [Đặc tả vé](../specs/booking.md#vé-điện-tử-và-qr).

## Hiển thị và dữ liệu

- Trang chủ và luồng mua vé dùng nền sáng, xanh mực cho điều hướng và cam ấm cho nút mua vé. Be Vietnam Pro dùng cho điều hướng, tiêu đề các bước, biểu mẫu và tên phim trong lưới. Barlow Condensed dùng cho nhận diện và tên phim trên banner. Sơ đồ ghế kết hợp màu và ký hiệu để phân biệt ghế thường, ghế cao cấp, ghế đã chọn và ghế hết chỗ.
- Trên laptop, thanh mua vé chồng lên mép dưới banner và lưới hiển thị bốn poster mỗi hàng. **Xem suất chiếu** điền sẵn phim trên banner vào thanh mua vé.
- Banner tự chuyển mỗi 7 giây. Khi người xem trỏ chuột lên banner, bộ đếm bỏ qua lần chuyển kế tiếp. Duyệt thủ công hoặc dùng bàn phím đi vào vùng banner sẽ dừng chế độ tự chuyển. Nút **Phát banner** bật lại. Nếu thiết bị bật giảm chuyển động, trang khởi động ở chế độ tạm dừng và bỏ hiệu ứng chuyển ảnh, phóng poster.
- Giao diện đọc suất từ `GET /api/screenings` và nhóm theo `movie_id`. Tất cả giờ chiếu hiển thị theo giờ Việt Nam. Phim chưa có ảnh hiển thị nền dự phòng.
- Banner và lưới poster dùng ảnh có sẵn từ Wikimedia Commons cho các phim đã xác minh. Xem nguồn trong trang [Nguồn ảnh phim](../cinema/web/films/credits.html). Hai phim hư cấu của đồ án tiếp tục dùng ảnh minh họa ImageGen.
- Có thể nhập tên phim có dấu hoặc không dấu. Bộ lọc trong mục **Phim** điều chỉnh lưới poster. Mỗi lượt chọn phòng hoặc ngày trong thanh mua vé sẽ tải lại các lựa chọn phụ thuộc.
- Bộ dữ liệu gồm 26 phim từng chiếu rạp, hai phim minh họa và 34 suất demo. Lệnh `uv run python -m cinema.setup --seed` nạp phim chiếu rạp từ `cinema/demo_movies.json` và giữ nguyên các suất đã tồn tại.
- Ảnh và phông được phục vụ từ `cinema/web/`. Giấy phép của Barlow Condensed và Be Vietnam Pro nằm cạnh các tệp phông.
- Giao diện dùng các endpoint Booking và Payment trong [hợp đồng API](../specs/contracts.md). Chạy các tình huống nghiệp vụ theo [kịch bản demo](demo.md).

## Đối chiếu trang chủ trên laptop

Ảnh chụp ngày 22/11/2026 ở 1366 × 900 px. Tọa độ tính từ mép trên ảnh.

| Vị trí | Galaxy Cinema | Chọn Suất trước | Chọn Suất sau |
| --- | ---: | ---: | ---: |
| Thanh mua vé | 483 px | 549 px | 472 px |
| Đầu lưới poster | 663 px | 791 px | 660 px |

- Galaxy Cinema dùng banner ngang, thanh mua vé bốn bước và bốn poster mỗi hàng. [Trang tham chiếu](https://www.galaxycine.vn/), [ảnh Galaxy Cinema](anh-doi-chieu/01-galaxy.jpg).
- Chọn Suất áp dụng cách tổ chức đó cho danh mục demo và giữ tên thương hiệu, hình ảnh phim và bộ lọc riêng. [Ảnh trước](anh-doi-chieu/02-chon-suat-truoc.jpg), [ảnh sau](anh-doi-chieu/03-chon-suat-sau.jpg).
