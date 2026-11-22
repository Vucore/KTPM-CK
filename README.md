# Chọn Suất

Đồ án đặt vé xem phim gồm ba tiến trình FastAPI. PostgreSQL chạy trên Supabase. RabbitMQ chuyển kết quả thanh toán và yêu cầu hoàn tiền giữa các service.

## Khởi động

1. Chuẩn bị một project Supabase, `uv` và Docker Compose hoặc một RabbitMQ có sẵn.
2. Tại thư mục đồ án, tạo môi trường và cấu hình.

   ```sh
   uv sync --locked
   cp .env.example .env
   uv run --locked python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. Trong `.env`, đặt `INTERNAL_API_KEY` bằng chuỗi ngẫu nhiên vừa tạo và `SUPABASE_DATABASE_URL` bằng chuỗi PostgreSQL lấy từ **Supabase → Connect → Session pooler** (cổng 5432). Mã hóa URL các ký tự đặc biệt trong mật khẩu và thêm `?sslmode=require` nếu chuỗi chưa có tham số SSL. Các giá trị này chỉ dùng bên backend. [Hướng dẫn kết nối Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres)
4. Áp dụng migration, nạp phim mẫu và chạy hệ thống.

   ```sh
   uv run --locked python -m cinema.setup --seed
   docker compose up -d rabbitmq
   uv run --locked python -m cinema.run
   ```

   Với RabbitMQ có sẵn, điền `RABBITMQ_URL` của broker vào `.env`. Mỗi lần nạp seed giữ nguyên suất mẫu đã có. Dùng project mới hoặc thêm suất tương lai khi các suất mẫu đã qua.
5. Mở [giao diện đặt vé](http://127.0.0.1:8000). Swagger phục vụ tại `/docs` của Booking (8000), Catalog (8001) và Payment (8002). Nhấn Ctrl+C để dừng ba tiến trình.

### Tách quyền trên Supabase

Mặc định ba service dùng chung DSN cho demo. Để cấp quyền riêng, tạo ba role có quyền đăng nhập và mật khẩu khác nhau trong Supabase. Chạy `uv run --locked python -m cinema.setup --runtime-roles cinema_catalog_app cinema_booking_app cinema_payment_app` với tên role thực tế. Điền DSN tương ứng vào `CATALOG_DATABASE_URL`, `BOOKING_DATABASE_URL`, `PAYMENT_DATABASE_URL`. Với Session pooler, username có dạng `role.project-ref`. Role Catalog chỉ đọc. Booking và Payment chỉ được đọc, thêm và cập nhật bảng trong schema được cấp. Giữ ba schema ngoài danh sách schema được xuất qua Supabase Data API.

## Kiểm tra

```sh
uv run --locked pytest -q
uv run --locked ruff check cinema tests
node --check cinema/web/app.js
```

Đặt `TEST_DATABASE_URL` trỏ tới PostgreSQL thử nghiệm riêng để chạy các bài kiểm tra tích hợp. Chúng tự áp dụng migration, tạo các suất ngẫu nhiên, gọi cả ba API qua test client và dùng broker giả lập để tái hiện tình huống gián đoạn. Xem [demo](docs/demo.md) để chạy qua RabbitMQ thật.

## Tài liệu

- [Quy tắc đặt vé](specs/booking.md) và [hợp đồng API, sự kiện](specs/contracts.md)
- [Kiến trúc](docs/architecture.md) và [sáu design pattern](docs/patterns.md)
- [Kịch bản demo](docs/demo.md) và [kế hoạch](KE_HOACH.md)
