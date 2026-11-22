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

Giá, ghế và vé thuộc Booking. Mỗi service giới hạn câu SQL trong schema riêng. Booking và Payment dùng outbox, RabbitMQ publisher confirm và consumer acknowledge sau commit để phục hồi khi mất kết nối.
