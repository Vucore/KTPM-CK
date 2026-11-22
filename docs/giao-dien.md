# Giao diện Chọn Suất

## Luồng đặt vé

1. Dùng **Đặt vé nhanh** để chọn phim và suất, hoặc bấm giờ chiếu trong **Phim & lịch chiếu**.
2. Chọn tối đa 8 ghế và nhập tên trên vé nếu muốn. Sơ đồ cập nhật qua SSE và tải lại định kỳ. Nếu ghế vừa bị giữ hoặc bán, giao diện cập nhật trạng thái để khách chọn lại.
3. Booking trả về tổng tiền và thời hạn giữ ghế. Trong **Thanh toán giả lập**, chọn kết quả và độ trễ để chạy giao dịch. Nếu kết quả bị từ chối, khách có thể thử lại khi thời hạn còn hiệu lực.
4. Khi Booking xác nhận đơn, mỗi ghế có một vé và một QR riêng. Mở lại đường dẫn `/?booking=<mã đơn>` để xem đơn hoặc vé đã cấp.

## Hiển thị và dữ liệu

- Phần lịch chiếu dùng nền trắng ngà, chữ xanh mực và nút cam đất. Sơ đồ ghế dùng nền tối. Màu và ký hiệu cùng phân biệt ghế cao cấp, ghế đã chọn và ghế hết chỗ.
- Trên laptop, banner thu gọn theo chiều cao cửa sổ và lưới hiển thị bốn poster mỗi hàng. Banner có sáu phim để duyệt, với nút **Chọn suất chiếu** điền sẵn phim vào thanh đặt vé nhanh.
- Giao diện đọc suất từ `GET /api/screenings` và nhóm theo `movie_id`. Tất cả giờ chiếu hiển thị theo giờ Việt Nam. Phim chưa có ảnh hiển thị nền dự phòng.
- Banner và lưới poster dùng ảnh có sẵn từ Wikimedia Commons cho các phim đã xác minh. Xem nguồn trong trang [Nguồn ảnh phim](../cinema/web/films/credits.html). Hai phim hư cấu của đồ án tiếp tục dùng ảnh minh họa ImageGen.
- Có thể nhập tên phim có dấu hoặc không dấu. Bộ lọc theo ngày tác động đến lưới lịch chiếu. Thanh đặt vé nhanh vẫn liệt kê mọi suất của phim đã chọn.
- Bộ dữ liệu gồm 26 phim từng chiếu rạp, hai phim minh họa và 34 suất demo. Lệnh `uv run python -m cinema.setup --seed` nạp phim chiếu rạp từ `cinema/demo_movies.json` và giữ nguyên các suất đã tồn tại.
- Ảnh và phông được phục vụ từ `cinema/web/`. Giấy phép của Barlow Condensed và Be Vietnam Pro nằm cạnh các tệp phông.
- Giao diện dùng các endpoint Booking và Payment trong [hợp đồng API](../specs/contracts.md). Chạy các tình huống nghiệp vụ theo [kịch bản demo](demo.md).
