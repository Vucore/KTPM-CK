# Hướng dẫn kiểm thử phân quyền (Authorization Testing)

Tài liệu này hướng dẫn cách kiểm thử hệ thống phân quyền RBAC, cô lập dữ liệu (chống IDOR), bảo vệ quy trình đặt vé/thanh toán và ranh giới giữa các microservice trong dự án **DUT Cinema / Chọn Suất**.

---

## 1. Vai trò & Tài khoản kiểm thử

Hệ thống định nghĩa 4 mức truy cập (kiểm chứng tại [api.py](../cinema/booking/api.py) và [contracts.py](../cinema/contracts.py)):

| Vai trò | Cách xác thực | Tài khoản mẫu (tạo bởi `python -m cinema.setup --seed`) |
|---|---|---|
| `Guest` | Chưa đăng nhập, dùng cookie trình duyệt `chon_suat_browser` (`HttpOnly`, `SameSite=Lax`) | Không cần tài khoản |
| `USER` | Đăng nhập cookie `chon_suat_session` (`HttpOnly`, `SameSite=Lax`) | Tự đăng ký qua `POST /api/auth/register` (mật khẩu tối thiểu 15 ký tự) |
| `STAFF` | Đăng nhập cookie `chon_suat_session`, `role = 'STAFF'` | `staff` / `dut-cinema-staff-2026` |
| `ADMIN` | Đăng nhập cookie `chon_suat_session`, `role = 'ADMIN'` | `admin` / `dut-cinema-admin-2026` |

> **Lưu ý an toàn:** Luôn chạy kiểm thử trên môi trường phát triển hoặc database test riêng (`TEST_DATABASE_URL`), không xóa dữ liệu hoặc gửi tải lớn lên database thật.

---

## 2. Ma trận phân quyền thực tế

| Nhóm chức năng / Endpoint | Guest | USER | STAFF | ADMIN | Ghi chú |
|---|---|---|---|---|---|
| Trang chủ, danh mục phim, lịch chiếu, sơ đồ ghế (`GET /`, `/api/screenings`, `/api/catalog/home`, `/api/movies/{id}`, `/api/screenings/{id}/seats`) | Allow | Allow | Allow | Allow | Công khai |
| Giữ ghế, xem đơn, chọn combo/promo, hủy giữ, thanh toán mô phỏng (`/api/holds`, `/api/checkout`, `/api/bookings/{id}*`) | Own (theo trình duyệt `hold_owner`) | Own (theo `account_id` hoặc `browser_key` cùng trình duyệt) | Own | Own | Người lạ nhận `404` trên cả `GET` lẫn thao tác ghi |
| Đổi điểm D-Star (`redeem_points > 0`) | Deny (`401`) | Allow (điểm của mình) | Allow | Allow | Bắt buộc đăng nhập |
| Lịch sử đặt vé (`/api/my-bookings*`) | Own (phạm vi `browser`) | Own (phạm vi `account`) | Own | Own | Cô lập theo session/browser |
| Tra cứu chi tiết vé & mã QR (`GET /api/tickets/{code}`, `/qr.svg`) | Own (nếu là đơn Guest cùng trình duyệt) | Own | Allow (tất cả vé) | Allow (tất cả vé) | Người lạ nhận `404`; không trả `booking_id` |
| Hồ sơ cá nhân & đổi mật khẩu (`GET/PATCH /api/account/profile`, `POST /api/account/password`) | Deny (`401`) | Own | Own | Own | Lấy `account_id` từ session; đổi mật khẩu thu hồi các phiên thiết bị khác và có rate-limit (`429`) |
| Xem danh sách đơn & Check-in vé QR (`GET /api/admin/bookings`, `POST /api/admin/tickets/{code}/check-in`) | Deny (`401`) | Deny (`403`) | Allow | Allow | `STAFF` có 2 tab riêng trên UI (**Đơn đặt vé** và **Soát vé QR**); vé đã check-in trả `409` khi quét lại |
| Doanh thu, quản lý phim/rạp/phòng/suất/bắp nước/KM/blog (`/api/admin/overview`, `/api/admin/catalog`, CRUD `/api/admin/*`) | Deny (`401`) | Deny (`403`) | Deny (`403`) | Allow | Bảo vệ cả Backend lẫn Frontend |
| Danh sách & phân quyền tài khoản (`GET /api/admin/accounts`, `PATCH /api/admin/accounts/{id}/role`) | Deny (`401`) | Deny (`403`) | Deny (`403`) | Allow | Chặn tự hạ quyền & hạ quyền `ADMIN` cuối cùng (`409`) |
| API nội bộ Catalog (`/admin/*`, cổng `8001`) & Payment (`/payments*`, cổng `8002`) | Deny (`403`) | Deny (`403`) | Deny (`403`) | Deny (`403`) | Chỉ cho phép request có header `X-Internal-Key` hợp lệ |

---

## 3. Chạy kiểm thử phân quyền tự động (Khuyến nghị)

Bộ test phân quyền nằm tại [test_authorization.py](../tests/test_authorization.py).

### 3.1. Chạy nhanh không cần PostgreSQL test

Các test sử dụng harness in-memory gắn trực tiếp vào các router FastAPI thật (`booking`, `catalog`, `payment`) nên có thể chạy ngay mà không làm thay đổi dữ liệu trong `.env`:

```powershell
.venv\Scripts\pytest.exe tests/test_authorization.py -v
```

Hoặc dùng `uv`:

```sh
UV_CACHE_DIR=.uv-cache uv run --locked pytest tests/test_authorization.py -v
```

Các nhóm ca kiểm thử được tự động kiểm chứng:
1. `test_auth_and_guest_vs_protected_routes` (`AUTH-001`..`AUTH-012`): quyền công khai của `Guest`, mã `401` trên endpoint yêu cầu đăng nhập và chặn `Guest` đổi điểm D-Star.
2. `test_user_and_staff_rbac_across_all_admin_routes` (`USER-012`..`018`, `STAFF-004`..`013`): xác nhận `USER` và `STAFF` bị trả `403` trên toàn bộ endpoint và HTTP method (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`) chỉ dành cho `ADMIN`.
3. `test_admin_role_management_and_last_admin_protection` (`ADMIN-002`, `ADMIN-008`, `ADMIN-016`): đổi role hợp lệ, chặn Admin tự hạ quyền (`409`) và chặn hạ quyền Quản trị viên cuối cùng (`409`).
4. `test_idor_for_bookings_checkout_and_tickets` (`IDOR-001`..`007`, `USER-008`): kiểm tra chéo tài khoản và chéo trình duyệt (kể cả đơn `Guest` tạo qua `/api/checkout`) đều nhận `404` khi truy cập đơn/vé/QR của người khác; `STAFF` vẫn soi và check-in được vé hợp lệ.
5. `test_server_side_pricing_csrf_origin_and_http_methods` (`API-015`, `BOOK-006`..`009`): chặn `Origin` giả mạo (`403`), chặn HTTP method không hỗ trợ (`405`), và tính lại giá ghế/combo ở server khi client gửi kèm `price`/`amount`/`discount_amount` giả.
6. `test_internal_service_key_boundaries`: xác nhận `Catalog` (`/admin/*`) và `Payment` (`/payments*`) trả `403` nếu thiếu hoặc sai `X-Internal-Key`.

### 3.2. Chạy kèm kiểm thử tích hợp PostgreSQL thật (`TEST_DATABASE_URL`)

Để chạy thêm `test_live_authorization_matrix` cùng toàn bộ test tích hợp trong `tests/test_admin.py`, `tests/test_checkout.py`, `tests/test_galaxy_user.py`, `tests/test_staged_checkout.py`, hãy trỏ `TEST_DATABASE_URL` vào một database PostgreSQL **dùng riêng cho test**:

**PowerShell:**

```powershell
$env:TEST_DATABASE_URL = "postgresql://user:password@127.0.0.1:5432/cinema_test"
.venv\Scripts\pytest.exe -v
```

**Bash / macOS / Linux:**

```sh
TEST_DATABASE_URL="postgresql://user:password@127.0.0.1:5432/cinema_test" uv run --locked pytest -v
```

---

## 4. Kiểm thử thủ công qua Giao diện & API (`curl` / PowerShell)

Khi chạy 3 dịch vụ bằng `python -m cinema.run` (`Booking` ở `http://127.0.0.1:8000`):

### 4.1. Kiểm tra truy cập URL & API trái phép (`AUTH-*`, `URL-*`, `USER-*`, `STAFF-*`)

1. Mở trình duyệt ẩn danh (hoặc dùng `curl`) truy cập trực tiếp `http://127.0.0.1:8000/?view=admin` → Giao diện hiển thị thông báo từ chối truy cập.
2. Kiểm tra Backend từ chối không phụ thuộc vào UI:

```sh
# Guest gọi API quản trị -> phải trả 401
curl -i http://127.0.0.1:8000/api/admin/overview

# Đăng nhập USER và lưu cookie vào user.cookies
curl -c user.cookies -X POST http://127.0.0.1:8000/api/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"<user_test>\",\"password\":\"<mat_khau_15_ky_tu>\"}"

# USER gọi API quản trị / soát vé / tự nâng quyền -> tất cả phải trả 403
curl -i -b user.cookies http://127.0.0.1:8000/api/admin/overview
curl -i -b user.cookies http://127.0.0.1:8000/api/admin/bookings
curl -i -b user.cookies -X POST http://127.0.0.1:8000/api/admin/movies -H "Content-Type: application/json" -d "{}"
curl -i -b user.cookies -X PATCH http://127.0.0.1:8000/api/admin/accounts/<user_id>/role -H "Content-Type: application/json" -d "{\"role\":\"ADMIN\"}"
```

3. Đăng nhập tài khoản `staff` (`staff.cookies`):
   - `GET /api/admin/bookings` → `200`
   - `GET /api/admin/overview` hoặc `PATCH /api/admin/accounts/<id>/role` → `403`

### 4.2. Kiểm tra IDOR đơn đặt vé & vé QR (`IDOR-*`, `BOOK-*`)

1. Dùng tài khoản `User A` (hoặc `Guest A`) đặt một đơn để lấy `booking_id` và `ticket_code`.
2. Dùng cookie của `User B` (hoặc trình duyệt ẩn danh `Guest B`) gọi:
   - `GET /api/bookings/<booking_id>` → phải trả `404` (nếu là đơn của `User A`).
   - `POST /api/bookings/<booking_id>/cancel` → phải trả `404` (cho cả đơn `User A` và `Guest A`).
   - `GET /api/tickets/<ticket_code>` và `GET /api/tickets/<ticket_code>/qr.svg` → phải trả `404`.

### 4.3. Kiểm tra giả mạo giá, Origin & dịch vụ nội bộ (`API-*`, `BOOK-009`)

```sh
# Giả mạo Origin khác domain -> phải trả 403
curl -i -b user.cookies -X POST http://127.0.0.1:8000/api/holds ^
  -H "Origin: https://attacker.example" -H "Idempotency-Key: 11111111-1111-1111-1111-111111111111" ^
  -H "Content-Type: application/json" -d "{\"screening_id\":\"saigon-evening\",\"seats\":[\"A1\"]}"

# Gọi trực tiếp Catalog /admin hoặc Payment không có X-Internal-Key -> phải trả 403
curl -i http://127.0.0.1:8001/admin/catalog
curl -i http://127.0.0.1:8002/payments/11111111-1111-1111-1111-111111111111
```

---

## 5. Giới hạn phạm vi hiện tại (các tính năng chưa triển khai)

Khi đối chiếu với ma trận kiểm thử chuẩn đầy đủ, các mục sau hiện **chưa có tính năng tương ứng** trong hệ thống:

- `ADMIN-003`..`ADMIN-007`: Admin tạo mới, chỉnh sửa hồ sơ, khóa/mở khóa hoặc xóa tài khoản người dùng khác (hiện chỉ có danh sách tài khoản và đổi role).
- `ADMIN-015`: Cấu hình tham số hệ thống qua giao diện/API quản trị (hiện cấu hình qua `.env`).
- `STAFF-014`: Giới hạn `STAFF` chỉ xem đơn và soát vé trong phạm vi một rạp được phân công (hiện `STAFF` xem được danh sách tối đa 100 đơn và soát vé trên toàn hệ thống).
