# Design pattern trong code

| Pattern | Lớp và vai trò | Kiểm tra |
|---|---|---|
| Strategy | `Pricing` chọn `WeekdayPricing` hay `WeekendPricing`. | Unit test ngày chiếu theo giờ Việt Nam. |
| State | `HeldState`, `ConfirmedState`, `ExpiredState` trả hành động phù hợp khi nhận thanh toán. | Kiểm tra đúng hạn, trễ hạn và giao lại. |
| Builder | `TicketBuilder` tạo dữ liệu vé, hỗ trợ tên khách tùy chọn. | Xem vé QR có hoặc thiếu tên. |
| Adapter | `DemoPaymentAdapter` đổi mã kết quả `DemoProcessor` về giao diện `PaymentGateway`. | Chạy thành công, từ chối và hoàn tiền. |
| Facade | `CheckoutFacade` gọi use case giữ ghế, sau đó tạo phiên Payment. | Gửi lại cùng khóa và nhận cùng đơn, cùng phiên. |
| Observer | `BookingObservers` gọi `SeatMapObserver` và `log_confirmation` sau commit. | Giao diện nhận tín hiệu cập nhật ghế qua SSE và log ghi số ghế bán. |

`cinema.booking.api.create_app` khởi tạo và truyền các dependency vào constructor. Ví dụ `HoldSeatsUseCase(db, bookings, seats, pricing, catalog, hold_seconds)`. Use case quyết định điều kiện giữ ghế, `BookingRepository` và `ScreeningSeatRepository` thao tác SQL trong transaction mà use case mở.
