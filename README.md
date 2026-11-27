# Chọn Suất

Chọn Suất là đồ án đặt vé xem phim. Giao diện HTML, CSS và JavaScript được phục vụ bởi Booking, một trong ba dịch vụ FastAPI. Dữ liệu lưu trên Supabase PostgreSQL. RabbitMQ là dịch vụ chuyển sự kiện giữa Booking và Payment. Pika là thư viện Python dùng để kết nối với RabbitMQ.

## Tính năng

- Duyệt phim và banner, lọc lịch chiếu, mua vé theo phim, phòng, ngày và suất.
- Chọn tối đa 8 ghế. Booking giữ cả nhóm ghế trong một giao dịch PostgreSQL và xử lý xung đột khi nhiều người đặt cùng lúc.
- Thanh toán giả lập với kết quả thành công, từ chối hoặc hoàn tiền khi quá hạn. Khi đơn xác nhận, mỗi ghế có một vé QR.
- Đặt vé với tư cách khách và tra cứu lại bằng mã đơn. Đăng nhập trước khi đặt để xem lịch sử trên nhiều thiết bị. Quét QR lấy mã vé để tra cứu đúng một ghế. Phạm vi demo dừng ở tra cứu vé. [Luồng sử dụng](docs/giao-dien.md), [đặc tả tài khoản](specs/accounts.md).

## Chạy server với cấu hình đã có

Chạy từ thư mục gốc của dự án. Các bước dưới đây dùng file `.env`, môi trường `.venv` và schema Supabase đã thiết lập. Nếu vừa kéo về phiên bản có thư viện hoặc migration mới, chạy `UV_CACHE_DIR=.uv-cache uv sync --locked` và `UV_CACHE_DIR=.uv-cache uv run --locked python -m cinema.setup` trước khi chạy ứng dụng.

1. Khởi động RabbitMQ bằng một trong các cách sau.

   - Với Docker đang chạy, dùng `docker compose up -d rabbitmq`. Xem trạng thái bằng `docker compose ps rabbitmq`.
   - Nếu máy đã có bộ RabbitMQ của phiên demo, dùng `bash .runtime/start-broker.sh` trong một Terminal và chờ `Server startup complete`. Script này thuộc bộ cài cục bộ. Bản clone mới có thể dùng Docker Compose.
   - Nếu đã có broker riêng, đặt `RABBITMQ_URL` trong `.env` trỏ tới broker đó.

2. Mở Terminal khác và chạy cả ba dịch vụ.

   ```sh
   UV_CACHE_DIR=.uv-cache uv run --no-sync python -m cinema.run
   ```

3. Mở [giao diện Chọn Suất](http://127.0.0.1:8000/).
4. Khi dùng xong, nhấn **Ctrl+C** trong Terminal chạy `cinema.run` để dừng ba dịch vụ. Nếu tự khởi động RabbitMQ cho phiên này, nhấn **Ctrl+C** ở Terminal chạy broker hoặc dùng `docker compose stop rabbitmq` với Docker.

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

| Hiện tượng | Kiểm tra |
|---|---|
| Website tải được nhưng danh mục trống | Gọi `/api/screenings`. Nếu trả `[]`, kiểm tra Supabase còn suất tương lai hay không. |
| `/health` trả 503 | Kiểm tra DSN và quyền kết nối PostgreSQL của dịch vụ tương ứng. |
| Payment báo thành công nhưng đơn còn chờ vé | Kiểm tra RabbitMQ ở `RABBITMQ_URL` và log Booking, Payment để xem sự kiện đã được chuyển và xử lý chưa. |

## Thiết lập lần đầu

1. Chuẩn bị một project Supabase, `uv` và Docker Compose hoặc một RabbitMQ có sẵn. Ba dịch vụ có thể dùng chung project Supabase qua ba schema riêng.
2. Tại thư mục đồ án, tạo môi trường và cấu hình.

   ```sh
   UV_CACHE_DIR=.uv-cache uv sync --locked
   test -f .env || cp .env.example .env
   UV_CACHE_DIR=.uv-cache uv run --locked python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. Trong `.env`, đặt `INTERNAL_API_KEY` bằng chuỗi ngẫu nhiên vừa tạo và `SUPABASE_DATABASE_URL` bằng chuỗi PostgreSQL lấy từ **Supabase → Connect → Session pooler** (cổng 5432). Mã hóa URL các ký tự đặc biệt trong mật khẩu và thêm `?sslmode=require` nếu chuỗi chưa có tham số SSL. Các giá trị này chỉ dùng bên backend. [Hướng dẫn kết nối Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres)
4. Áp dụng migration và nạp phim mẫu.

   ```sh
   UV_CACHE_DIR=.uv-cache uv run --locked python -m cinema.setup --seed
   ```

   Lệnh nạp phim mẫu và giữ nguyên các suất đã có. Catalog chỉ trả về suất tương lai. Khi danh mục hết suất, cần tạo thêm suất có giờ chiếu trong tương lai.
5. Làm theo phần [Chạy server với cấu hình đã có](#chạy-server-với-cấu-hình-đã-có).

### Cấu hình dự án

| Biến | Dùng để |
|---|---|
| `SUPABASE_DATABASE_URL` | Kết nối PostgreSQL cho lệnh setup và DSN mặc định của ba dịch vụ. |
| `CATALOG_DATABASE_URL`, `BOOKING_DATABASE_URL`, `PAYMENT_DATABASE_URL` | Tùy chọn cấp DSN riêng theo vai trò của từng dịch vụ. |
| `INTERNAL_API_KEY` | Khóa dùng chung giữa Booking và Payment, tối thiểu 24 ký tự. |
| `RABBITMQ_URL` | Địa chỉ AMQP. Cấu hình demo dùng `127.0.0.1:5672`. |
| `CATALOG_URL`, `PAYMENT_URL` | Địa chỉ REST mà Booking gọi. Mặc định lần lượt là cổng 8001 và 8002. |
| `HOLD_SECONDS` | Thời hạn giữ ghế. Mặc định 300 giây, phạm vi 1–3600. |

`.env.example` và `uv.lock` nằm trong Git để người khác có thể dựng lại môi trường. `.env`, môi trường ảo, cache và thư mục `.runtime/` chứa bộ cài RabbitMQ cục bộ cùng dữ liệu thử nghiệm được loại khỏi Git.

### Tách quyền trên Supabase

Mặc định ba service dùng chung DSN cho demo. Để cấp quyền riêng, tạo ba role có quyền đăng nhập và mật khẩu khác nhau trong Supabase. Chạy `uv run --locked python -m cinema.setup --runtime-roles cinema_catalog_app cinema_booking_app cinema_payment_app` với tên role thực tế. Điền DSN tương ứng vào `CATALOG_DATABASE_URL`, `BOOKING_DATABASE_URL`, `PAYMENT_DATABASE_URL`. Với Session pooler, username có dạng `role.project-ref`. Role Catalog chỉ đọc. Booking và Payment được đọc, thêm và cập nhật bảng trong schema được cấp. Booking có thêm quyền xóa các dòng phiên, bộ đếm hết hạn và liên kết lịch sử. Giữ ba schema ngoài danh sách schema được xuất qua Supabase Data API.

## Kiểm tra

```sh
UV_CACHE_DIR=.uv-cache uv run --locked pytest -q
UV_CACHE_DIR=.uv-cache uv run --locked ruff check cinema tests
node --check cinema/web/app.js
```

Đặt `TEST_DATABASE_URL` trong môi trường Terminal và trỏ tới PostgreSQL thử nghiệm riêng. Các bài tích hợp tự áp dụng migration, tạo suất thử, gọi ba API qua test client và dùng broker giả lập để tái hiện gián đoạn. Nếu biến này chưa được đặt, pytest bỏ qua các bài cần PostgreSQL. Xem [kịch bản demo](docs/demo.md) để chạy qua RabbitMQ thật.

## Tài liệu

- [Quy tắc đặt vé](specs/booking.md) và [hợp đồng API, sự kiện](specs/contracts.md)
- [Tài khoản và lịch sử vé](specs/accounts.md)
- [Kiến trúc](docs/architecture.md) và [sáu design pattern](docs/patterns.md)
- [Giao diện và luồng đặt vé](docs/giao-dien.md)
- [Kiểm thử phân quyền (Authorization Testing)](docs/kiem-thu-phan-quyen.md)
- [Kịch bản demo](docs/demo.md) và [kế hoạch](KE_HOACH.md)
