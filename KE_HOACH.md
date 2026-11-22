# Kế hoạch thực hiện đồ án đặt vé xem phim

## 1. Mục tiêu và phạm vi

Khách chọn một suất chiếu, xem ghế trống, giữ một hoặc nhiều ghế, thanh toán và nhận vé điện tử có mã QR. Đồ án cần chứng minh hai tính chất qua demo: mỗi ghế của một suất chỉ bán được một lần và khách được hoàn tiền nếu thanh toán thành công sau khi đơn hết hạn.

Phương án triển khai dùng Python với FastAPI, PostgreSQL trên Supabase và RabbitMQ. Dùng `uv` quản lý môi trường Python và Docker Compose chạy RabbitMQ. Dữ liệu phim và suất chiếu mẫu, cổng thanh toán giả lập và giao diện web hỗ trợ bốn bước chọn suất, chọn ghế, thanh toán và xem vé. Mặc định giữ ghế 5 phút và có thể rút ngắn khi demo.

## 2. Kiến trúc và quyền sở hữu dữ liệu

| Service | Trách nhiệm | Schema Supabase |
|---|---|---|
| Catalog | Cung cấp phim, phòng, sơ đồ ghế và lịch chiếu. Khi mở bán, cung cấp danh sách ghế của suất cho Booking. | `cinema_catalog` |
| Booking | Tạo tồn ghế theo suất, tính và chốt giá, giữ ghế, quản lý đơn, phát hành vé QR. Đây là nơi quyết định ghế nào còn bán được. | `cinema_booking` |
| Payment | Tạo phiên thanh toán theo mã đơn và số tiền do Booking cung cấp, ghi nhận kết quả, xử lý hoàn tiền. | `cinema_payment` |

Dùng một project Supabase với ba schema riêng. Có thể cấp một tài khoản database cho mỗi schema theo README. Các service gọi REST khi cần trả lời ngay. Payment gửi kết quả thanh toán qua RabbitMQ, Booking gửi yêu cầu hoàn tiền theo chiều ngược lại. Mỗi service chỉ truy cập dữ liệu thuộc schema của mình.

## 3. Design pattern, DI và Repository

| Pattern | Vị trí triển khai | Cách chứng minh |
|---|---|---|
| Strategy | Booking dùng `PricingStrategy` để chọn giá thường hoặc giá cuối tuần theo ngày chiếu. | Cùng loại ghế, đổi ngày chiếu thì nhận đúng mức giá. |
| State | Đơn ở trạng thái `HELD`, `CONFIRMED` hoặc `EXPIRED`. Mỗi lớp trạng thái xử lý việc xác nhận hoặc hết hạn. | Đơn đang giữ có thể phát hành vé, đơn đã hết hạn chỉ có thể dẫn đến hoàn tiền nếu đã thu tiền. |
| Builder | `TicketBuilder` tạo vé cho từng ghế từ mã vé, suất chiếu, số ghế và các trường tùy chọn như tên khách. | Tạo được vé có hoặc thiếu tên khách, QR chứa mã tra cứu đúng vé. |
| Adapter | Payment dùng `PaymentGateway`. Adapter chuyển yêu cầu thu hoặc hoàn tiền và mã kết quả của cổng giả lập sang kiểu dữ liệu nội bộ. | Mô phỏng thành công, từ chối hoặc trả kết quả muộn qua cùng interface. |
| Facade | `CheckoutFacade` cung cấp một thao tác bắt đầu đặt vé, phối hợp giữ ghế và tạo phiên thanh toán. | Giao diện nhận mã đơn, thời hạn giữ và phiên thanh toán qua một lời gọi. |
| Observer | Sau khi Booking xác nhận đơn và commit, các listener đăng ký nhận `BookingConfirmed` để cập nhật sơ đồ ghế trên giao diện và ghi thống kê demo. | Một lần xác nhận kích hoạt hai listener độc lập. |

Các use case nhận dependency qua constructor. Ví dụ, `HoldSeatsUseCase` nhận `ScreeningSeatRepository`, `BookingRepository` và thành phần tính giá. Unit test truyền repository giả để kiểm tra quy tắc nghiệp vụ. Integration test dùng PostgreSQL thật để kiểm tra transaction và tranh chấp ghế.

## 4. Thứ tự triển khai

Mỗi mốc gồm phần đặc tả cần viết trước khi code và tài liệu cần cập nhật sau khi đã chạy thử. Các đường dẫn bên dưới là đầu ra dự kiến của giai đoạn triển khai.

| Mốc | Công việc và tài liệu đi kèm | Tiêu chí hoàn thành |
|---|---|---|
| 1. Chốt nghiệp vụ | Viết `specs/booking.md` và `specs/contracts.md`. Thống nhất luồng thành công, hết hạn, thanh toán trễ, các trạng thái và hợp đồng REST/sự kiện. | Có ví dụ đầu vào, kết quả và lỗi cho từng luồng chính. |
| 2. Dựng nền và Catalog | Tạo ba ứng dụng FastAPI, migration Supabase, Compose cho RabbitMQ và dữ liệu mẫu. Vẽ sơ đồ trong `docs/architecture.md`. | Từ database rỗng, khởi động được ba service, xem được lịch chiếu và sơ đồ ghế. Khi đồng bộ lại cùng suất, ghế đang giữ vẫn thuộc đơn cũ. |
| 3. Giữ ghế và chốt giá | Làm Repository, DI, Strategy và State. Tạo đơn và giữ toàn bộ ghế trong một transaction. Lưu giá tại lúc giữ, xử lý hết hạn, cập nhật `specs/booking.md`. | Hai yêu cầu cùng giữ A5 chỉ có một yêu cầu thành công, yêu cầu kia nhận HTTP 409. Nếu một ghế trong nhóm bị chiếm thì cả nhóm được rollback. |
| 4. Thanh toán và phối hợp service | Làm Adapter, Facade, phiên thanh toán, xử lý sự kiện và hoàn tiền. Lưu sự kiện cần gửi trong cùng transaction với thay đổi nghiệp vụ, gửi lại khi RabbitMQ phục hồi. Cập nhật ví dụ thực tế vào `specs/contracts.md`. | Thử lại yêu cầu với cùng khóa trả về cùng đơn và phiên thanh toán. Sự kiện giao lặp không tạo thêm vé hoặc hoàn tiền hai lần. Thanh toán trễ dẫn đến hoàn tiền. |
| 5. Vé và giao diện | Làm Builder, Observer và bốn bước giao diện. Hiển thị thời hạn giữ từ server và cho khách chọn lại ghế khi gặp 409. Ghi vị trí các lớp và bài test minh họa vào `docs/patterns.md`. | Khách hoàn thành luồng từ chọn suất đến xem QR. Mỗi ghế đã mua có đúng một vé. Mở lại đơn đã xác nhận vẫn xem được vé cũ. |
| 6. Kiểm thử tích hợp và bàn giao | Chạy các kịch bản ở mục 6, hoàn thiện `README.md` và `docs/demo.md` từ lệnh đã chạy thực tế. | Một thành viên khác có thể khởi động hệ thống từ đầu và tái hiện các kịch bản bằng tài liệu. |

## 5. Nội dung tối thiểu của các file tài liệu

| File dự kiến | Nội dung cần tra cứu |
|---|---|
| `specs/booking.md` | Ai được làm gì, bảng chuyển trạng thái đơn/ghế, quy tắc giá, giữ nhiều ghế, thời điểm hết hạn và điều kiện cấp vé hoặc hoàn tiền. |
| `specs/contracts.md` | Service sở hữu từng endpoint hoặc sự kiện, payload mẫu, mã lỗi, khóa chống xử lý lặp và cách thử lại. Ghi rõ nguồn số tiền và mã đơn dùng để đối chiếu. |
| `docs/architecture.md` | Một sơ đồ service/database và một sơ đồ tuần tự từ giữ ghế đến phát hành vé, có nhánh thanh toán trễ. |
| `docs/patterns.md` | Sáu dòng tương ứng sáu pattern, mỗi dòng nêu vấn đề, lớp thực hiện và ví dụ chạy thử. Thêm một ví dụ constructor injection nối use case với repository. |
| `README.md` | Điều kiện chạy, cấu hình mẫu, lệnh khởi động, nạp dữ liệu, truy cập giao diện và chạy test. |
| `docs/demo.md` | Dữ liệu đầu vào, thao tác và kết quả mong đợi cho từng kịch bản nghiệm thu. |

Ưu tiên bảng, ví dụ request/response ngắn và đường dẫn đến code. Mỗi quy tắc có một nơi mô tả chính. Khi code thay đổi hành vi, cập nhật đặc tả và ví dụ liên quan trong cùng lần sửa.

## 6. Kịch bản nghiệm thu

| Tình huống | Kết quả cần kiểm tra |
|---|---|
| Hai khách cùng đặt ghế A5 của một suất | Một đơn giữ được ghế. Khách còn lại nhận 409. A5 của suất khác vẫn đặt được. |
| Khách chọn A4 và A5, trong đó A5 đã bị giữ | Cả yêu cầu thất bại và A4 vẫn trống. |
| Thanh toán thành công trong hạn | Booking xác nhận đơn, bán đúng các ghế đã giữ và tạo một vé cho mỗi ghế trong cùng transaction. |
| Thanh toán bị từ chối | Khách thấy giao dịch thất bại và có thể thử lại trong thời hạn giữ. Đến hạn, hệ thống giải phóng ghế chưa bán. |
| Thanh toán thành công sau hạn | Dù tác vụ dọn ghế chưa kịp chạy, Booking kiểm tra thời hạn theo đồng hồ database, từ chối cấp vé và yêu cầu hoàn tiền. Nếu khách khác đã giữ ghế, lượt giữ mới được bảo toàn. |
| Gửi lại yêu cầu hoặc sự kiện sau mất kết nối | Hệ thống trả về kết quả đã ghi nhận hoặc tiếp tục phần việc còn dang dở. Số đơn, vé và khoản hoàn tiền khớp với giao dịch thực tế. |
| RabbitMQ tạm dừng sau khi Payment ghi nhận thành công | Khi broker hoạt động trở lại, sự kiện đã lưu được gửi tiếp. Booking xử lý theo trạng thái đơn và thời hạn giữ ghế lúc xác nhận. |
