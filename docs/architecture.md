# Kiến trúc

```mermaid
flowchart LR
    Web["Trình duyệt"] --> B["Booking · 8000"]
    B -->|REST| C["Catalog · 8001"]
    B -->|REST nội bộ| P["Payment · 8002"]
    B <-->|Sự kiện| R["RabbitMQ"]
    P <-->|Sự kiện| R
    subgraph Supabase["Supabase PostgreSQL"]
        CS["cinema_catalog"]
        BS["cinema_booking"]
        PS["cinema_payment"]
    end
    C --> CS
    B --> BS
    P --> PS
```

| Thành phần | Trách nhiệm |
|---|---|
| Booking | Phục vụ giao diện web, xác thực tài khoản, giữ ghế, quản lý lịch sử và phát hành vé. |
| Catalog | Cung cấp phim, phòng, suất tương lai và sơ đồ ghế gốc qua REST. |
| Payment | Tạo phiên thanh toán nội bộ, xử lý kết quả giả lập và hoàn tiền. |
| RabbitMQ | Chuyển sự kiện thanh toán và hoàn tiền giữa Booking và Payment qua AMQP. Hai dịch vụ kết nối broker bằng Pika. |
| Supabase PostgreSQL | Một database chứa ba schema nghiệp vụ. Booking quản lý bảng tài khoản và phiên trong `cinema_booking`. |

Trình duyệt gọi Booking. Booking đọc lịch chiếu từ Catalog và gọi Payment bằng `X-Internal-Key`. Kết quả thanh toán thành công được xử lý bất đồng bộ qua RabbitMQ.

```mermaid
sequenceDiagram
    participant U as Trình duyệt
    participant B as Booking
    participant P as Payment
    participant Q as RabbitMQ
    U->>B: Chọn ghế và checkout
    B->>B: Giữ toàn bộ ghế và commit
    B->>P: Tạo phiên theo mã đơn
    B-->>U: Trả đơn, hạn giữ và phiên
    U->>B: Giả lập thanh toán
    B->>P: Lên lịch trả kết quả
    P->>P: Ghi kết quả và outbox
    P->>Q: payment.succeeded
    Q->>B: payment.succeeded
    alt Còn hạn
        B->>B: Bán ghế và phát hành vé
        U->>B: Đọc đơn và nhận vé
    else Hết hạn
        B->>Q: payment.refund_requested
        Q->>P: payment.refund_requested
        P->>P: Ghi nhận hoàn tiền
    end
```

## Nhất quán dữ liệu và người dùng đồng thời

- Checkout khóa ghế theo suất và nhãn ghế trong PostgreSQL. Các ghế và liên kết lịch sử được ghi trong cùng giao dịch khi tạo đơn. Luật này áp dụng cho cả khách và người dùng đã đăng nhập.
- Booking và Payment lưu sự kiện vào outbox cùng giao dịch ghi trạng thái. RabbitMQ xác nhận việc nhận bản tin từ bên gửi. Bên nhận chỉ xác nhận đã xử lý sau khi giao dịch commit. Điều kiện trạng thái và khóa idempotency bảo vệ khi yêu cầu được gửi lại.
- Giao diện nhận tín hiệu SSE khi tiến trình Booking xử lý bán vé và tải lại sơ đồ mỗi 5 giây. PostgreSQL là nguồn trạng thái ghế dùng chung.
- Repository đóng gói truy vấn SQL theo schema. API dựng các repository và truyền vào use case, service qua constructor. [Design pattern](patterns.md), [hợp đồng API](../specs/contracts.md).
