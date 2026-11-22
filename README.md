# Chọn Suất

Đồ án đặt vé xem phim gồm ba tiến trình FastAPI. PostgreSQL chạy trên Supabase. RabbitMQ chuyển kết quả thanh toán và yêu cầu hoàn tiền giữa các service.

## Chạy server với cấu hình đã có

Chạy các lệnh từ thư mục gốc của dự án. Dùng `.env` và `.venv` đã thiết lập.

Sau khi cập nhật lên bản có đăng nhập, đồng bộ thư viện và áp dụng migration Supabase trước lần chạy đầu tiên.

```sh
uv sync --locked
uv run --locked python -m cinema.setup
```

1. Khởi động RabbitMQ nếu broker chưa chạy. Với Docker Compose, dùng `docker compose up -d rabbitmq`. Nếu máy đã có bản RabbitMQ của phiên demo trong `.runtime/`, chạy `bash .runtime/start-broker.sh` ở một terminal riêng và giữ terminal đó mở. Với broker có sẵn, đặt `RABBITMQ_URL` trong `.env` trỏ tới broker đó.
2. Mở terminal khác và chạy cả ba dịch vụ.

   ```sh
   uv run --no-sync python -m cinema.run
   ```

3. Mở [giao diện Chọn Suất](http://127.0.0.1:8000/). Nhấn Ctrl+C trong terminal chạy `cinema.run` để dừng ba tiến trình.

| Dịch vụ | Trách nhiệm | Swagger |
|---|---|---|
| Booking · 8000 | Phục vụ HTML, CSS, JavaScript và API đặt vé công khai. | [Booking](http://127.0.0.1:8000/docs) |
| Catalog · 8001 | Cung cấp phim, phòng và suất chiếu cho Booking qua REST. | [Catalog](http://127.0.0.1:8001/docs) |
| Payment · 8002 | Xử lý trạng thái thanh toán giả lập và hoàn tiền. | [Payment](http://127.0.0.1:8002/docs) |

Kiểm tra cả ba dịch vụ và dữ liệu Catalog.

```sh
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:8002/health
curl -fsS http://127.0.0.1:8000/api/screenings
```

Mỗi `/health` chạy một truy vấn PostgreSQL và trả `{"status":"ok"}` khi kết nối được. Để kiểm tra RabbitMQ và toàn bộ luồng, đặt một vé demo và chờ đơn chuyển sang `CONFIRMED`. Xem [kịch bản demo](docs/demo.md).

## Thiết lập lần đầu

1. Chuẩn bị một project Supabase, `uv` và Docker Compose hoặc một RabbitMQ có sẵn.
2. Tại thư mục đồ án, tạo môi trường và cấu hình.

   ```sh
   uv sync --locked
   test -f .env || cp .env.example .env
   uv run --locked python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. Trong `.env`, đặt `INTERNAL_API_KEY` bằng chuỗi ngẫu nhiên vừa tạo và `SUPABASE_DATABASE_URL` bằng chuỗi PostgreSQL lấy từ **Supabase → Connect → Session pooler** (cổng 5432). Mã hóa URL các ký tự đặc biệt trong mật khẩu và thêm `?sslmode=require` nếu chuỗi chưa có tham số SSL. Các giá trị này chỉ dùng bên backend. [Hướng dẫn kết nối Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres)
4. Áp dụng migration và nạp phim mẫu.

   ```sh
   uv run --locked python -m cinema.setup --seed
   ```

   Lệnh giữ nguyên các suất đã có. Nếu các suất mẫu đã qua, thêm suất tương lai để danh mục có dữ liệu.
5. Làm theo phần [Chạy server với cấu hình đã có](#chạy-server-với-cấu-hình-đã-có).

### Tách quyền trên Supabase

Mặc định ba service dùng chung DSN cho demo. Để cấp quyền riêng, tạo ba role có quyền đăng nhập và mật khẩu khác nhau trong Supabase. Chạy `uv run --locked python -m cinema.setup --runtime-roles cinema_catalog_app cinema_booking_app cinema_payment_app` với tên role thực tế. Điền DSN tương ứng vào `CATALOG_DATABASE_URL`, `BOOKING_DATABASE_URL`, `PAYMENT_DATABASE_URL`. Với Session pooler, username có dạng `role.project-ref`. Role Catalog chỉ đọc. Booking và Payment được đọc, thêm và cập nhật bảng trong schema được cấp. Booking có thêm quyền xóa các dòng phiên, bộ đếm hết hạn và liên kết lịch sử. Giữ ba schema ngoài danh sách schema được xuất qua Supabase Data API.

## Kiểm tra

```sh
uv run --locked pytest -q
uv run --locked ruff check cinema tests
node --check cinema/web/app.js
```

Đặt `TEST_DATABASE_URL` trỏ tới PostgreSQL thử nghiệm riêng để chạy các bài kiểm tra tích hợp. Chúng tự áp dụng migration, tạo các suất ngẫu nhiên, gọi cả ba API qua test client và dùng broker giả lập để tái hiện tình huống gián đoạn. Xem [demo](docs/demo.md) để chạy qua RabbitMQ thật.

## Tài liệu

- [Quy tắc đặt vé](specs/booking.md) và [hợp đồng API, sự kiện](specs/contracts.md)
- [Tài khoản và lịch sử vé](specs/accounts.md)
- [Kiến trúc](docs/architecture.md) và [sáu design pattern](docs/patterns.md)
- [Giao diện và luồng đặt vé](docs/giao-dien.md)
- [Kịch bản demo](docs/demo.md) và [kế hoạch](KE_HOACH.md)
