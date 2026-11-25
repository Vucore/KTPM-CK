from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from argon2 import PasswordHasher
from dotenv import load_dotenv
from psycopg import sql
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ("cinema_catalog", "cinema_booking", "cinema_payment")
SHOW_TIMES = ("10:30", "13:45", "17:15", "20:15")

PRICE_TABLE_2D = [
    {"label": "Người lớn (Thứ 2 - Thứ 5)", "standard": "75.000 ₫", "vip": "95.000 ₫", "couple": "185.000 ₫"},
    {"label": "Cuối tuần (Thứ 6 - CN & Lễ)", "standard": "90.000 ₫", "vip": "110.000 ₫", "couple": "215.000 ₫"},
    {"label": "Thành viên U22 / HSSV", "standard": "55.000 ₫", "vip": "75.000 ₫", "couple": "150.000 ₫"},
    {"label": "Happy Day (Thứ 2 đầu tháng)", "standard": "50.000 ₫", "vip": "70.000 ₫", "couple": "140.000 ₫"},
]

PRICE_TABLE_IMAX = [
    {"label": "2D Thường (Thứ 2 - Thứ 5)", "standard": "85.000 ₫", "vip": "105.000 ₫", "couple": "205.000 ₫"},
    {"label": "2D Cuối tuần (Thứ 6 - CN)", "standard": "100.000 ₫", "vip": "120.000 ₫", "couple": "235.000 ₫"},
    {"label": "IMAX 2D (Các ngày trong tuần)", "standard": "140.000 ₫", "vip": "160.000 ₫", "couple": "315.000 ₫"},
    {"label": "Thành viên U22 (2D)", "standard": "60.000 ₫", "vip": "80.000 ₫", "couple": "160.000 ₫"},
]

CINEMAS = [
    (
        "dut-nguyen-du",
        "DUT Nguyễn Du",
        "TP.HCM",
        "116 Nguyễn Du, P. Bến Thành, Quận 1, TP.HCM",
        "1900 2224",
        ["2D", "3D", "Dolby Atmos"],
        "08:30 - 23:45",
        PRICE_TABLE_2D,
    ),
    (
        "dut-sala",
        "DUT Sala",
        "TP.HCM",
        "Tầng 3, Thiso Mall Sala, 10 Mai Chí Thọ, TP. Thủ Đức, TP.HCM",
        "1900 2224",
        ["2D", "IMAX", "Cine de Kids"],
        "08:30 - 24:00",
        PRICE_TABLE_IMAX,
    ),
    (
        "dut-danang",
        "DUT Đà Nẵng",
        "Đà Nẵng",
        "54 Nguyễn Lương Bằng, Q. Liên Chiểu, Đà Nẵng",
        "1900 2224",
        ["2D", "3D"],
        "08:45 - 23:30",
        PRICE_TABLE_2D,
    ),
    (
        "dut-mipec",
        "DUT Mipec Long Biên",
        "Hà Nội",
        "Tầng 6, Mipec Riverside, Số 2 Long Biên II, Q. Long Biên, Hà Nội",
        "1900 2224",
        ["2D", "3D", "IMAX"],
        "08:30 - 23:30",
        PRICE_TABLE_IMAX,
    ),
]

AUDITORIUMS = [
    ("room-1", "Phòng 1 · Nguyễn Du", "dut-nguyen-du", "2D Phụ đề"),
    ("room-2", "Phòng IMAX · Sala", "dut-sala", "IMAX 2D"),
    ("room-3", "Phòng 2 · Đà Nẵng", "dut-danang", "2D Phụ đề"),
    ("room-4", "Phòng 3 · Long Biên", "dut-mipec", "2D Lồng tiếng"),
]

CONCESSIONS = [
    ("combo-1-big", "Combo 1 Big", "1 Bắp Ngọt Lớn + 1 Pepsi Tươi Lớn", 89000, "Combo", "Bán chạy", 1),
    ("combo-2-big", "Combo 2 Big", "1 Bắp Phô Mai / Caramel Lớn + 2 Pepsi Tươi Lớn", 119000, "Combo", "Tiết kiệm", 2),
    ("combo-u22", "Combo U22", "1 Bắp Ngọt Vừa + 1 Nước Ngọt Vừa (Ưu đãi HSSV)", 69000, "Combo", "U22", 3),
    ("combo-imax", "Combo IMAX Voyage", "1 Bắp Milo Lớn + 2 Nước Lớn + Túi đựng ly phiên bản rạp", 169000, "Combo", "Đặc biệt", 4),
    ("popcorn-caramel", "Bắp Caramel Lớn", "Bắp rang bơ phủ caramel giòn thơm nóng hổi", 55000, "Đồ ăn", None, 5),
    ("pepsi-large", "Pepsi Tươi Lớn (32oz)", "Nước ngọt có ga mát lạnh cỡ lớn", 39000, "Thức uống", None, 6),
]

PROMOTIONS = [
    (
        "promo-happy-day",
        "Happy Day - Thứ Hai Đầu Tháng Giá Vé Chỉ Từ 50K",
        "Ngày Tri Ân",
        "Thứ Hai đầu tiên mỗi tháng, đồng giá vé 2D và tặng 1 lần refill bắp ngọt/nước ngọt trước 22:00.",
        "HAPPYDAY",
        "FIXED",
        25000,
        75000,
        "Thứ 2 đầu tiên mỗi tháng",
        "Áp dụng giảm ngay 25.000 ₫ cho đơn vé từ 75.000 ₫ khi nhập mã HAPPYDAY khi đặt trực tuyến.",
        1,
    ),
    (
        "promo-u22",
        "Đặc Quyền Thành Viên U22 - Giá Vé Sinh Viên Từ 55K",
        "Ưu đãi U22",
        "Dành cho khán giả từ 22 tuổi trở xuống với ưu đãi vé xem phim và Combo U22 siêu tiết kiệm.",
        "U22SALE",
        "FIXED",
        20000,
        70000,
        "Áp dụng cả tuần",
        "Nhập mã U22SALE để được giảm 20.000 ₫ cho đơn hàng từ 70.000 ₫. Xuất trình CCCD/Thẻ HSSV tại quầy soát vé.",
        2,
    ),
    (
        "promo-dut20",
        "Ưu Đãi Đặt Vé Online - Nhập Mã DUT20 Giảm 20%",
        "Khuyến mãi Online",
        "Giảm 20% tổng giá trị đơn hàng (ghế + bắp nước) khi đặt vé trực tuyến qua website.",
        "DUT20",
        "PERCENT",
        20,
        100000,
        "31/12/2026",
        "Áp dụng cho mọi suất chiếu 2D và IMAX có tổng giá trị đơn từ 100.000 ₫ trở lên.",
        3,
    ),
    (
        "promo-combo15",
        "Đặt Kèm Bắp Nước Online - Giảm Ngay 15.000 ₫",
        "Bắp Nước",
        "Mua vé kèm Combo 1 Big hoặc Combo 2 Big giảm thêm 15.000 ₫ trực tiếp vào hóa đơn.",
        "COMBO15",
        "FIXED",
        15000,
        140000,
        "31/12/2026",
        "Áp dụng cho đơn đặt vé kèm bắp nước có tổng thanh toán từ 140.000 ₫.",
        4,
    ),
    (
        "promo-dstar",
        "Quyền Lợi Thành Viên D-Star & X-Star",
        "Thành viên",
        "Tích lũy 1 Star cho mỗi 10.000 ₫ chi tiêu, quà tặng Combo 2 trong tháng sinh nhật và vé 2D miễn phí khi lên hạng.",
        None,
        "INFO",
        0,
        0,
        "Quanh năm",
        "Đăng ký tài khoản miễn phí để tự động tích điểm Star trên mỗi giao dịch vé đã xác nhận và đổi điểm giảm giá trực tiếp.",
        5,
    ),
]

BLOG_POSTS = [
    (
        "review-saigon",
        "review",
        "[Review] Sài Gòn Sau Mưa: Bản tình ca dịu dàng giữa những con hẻm Sài Thành",
        "Một câu chuyện tình nhẹ nhàng nhưng day dứt với nhịp phim chậm rãi, ánh đèn đường phản chiếu qua mặt nước và diễn xuất tinh tế.",
        "Sài Gòn Sau Mưa không cố tạo cao trào kịch tính bằng những biến cố ồn ào. Đạo diễn chọn cách để hai nhân vật đi bộ dọc những con phố quen thuộc sau cơn mưa đầu mùa, nơi từng câu thoại ngắn gợi mở ký ức cũ. Phần âm thanh tiếng mưa và nhạc nền tối giản giúp khán giả dễ dàng đồng cảm. Phù hợp với những buổi tối cuối tuần muốn tìm một tác phẩm giàu cảm xúc.",
        "Minh Anh",
        "2 ngày trước",
        "saigon",
        4820,
        1,
    ),
    (
        "review-orbit",
        "review",
        "[Review] Quỹ Đạo Cuối: Nghẹt thở từng phút trên màn ảnh IMAX",
        "Âm thanh vòm và khung hình rộng của phòng chiếu IMAX nâng tầm trải nghiệm sinh tồn ngoài không gian của Quỹ Đạo Cuối.",
        "Ngay từ cảnh mở đầu khi trạm nghiên cứu mất kết nối với mặt đất, Quỹ Đạo Cuối đã thiết lập bầu không khí căng thẳng liên tục. Điểm sáng của phim nằm ở cách giải quyết sự cố mang tính kỹ thuật thực tế thay vì phép màu. Nếu có thể, hãy chọn suất IMAX 2D để cảm nhận trọn vẹn chiều sâu của không gian vũ trụ và hiệu ứng âm thanh rung chuyển ghế.",
        "Quốc Bảo",
        "4 ngày trước",
        "orbit",
        6310,
        2,
    ),
    (
        "review-metropolis",
        "review",
        "[Review] Metropolis (Phiên bản phục chế): Kiệt tác khoa học viễn tưởng vượt thời gian",
        "Gần một thế kỷ trôi qua, kiến trúc tương lai và thông điệp nhân văn của Metropolis vẫn khiến người xem choáng ngợp.",
        "Được trình chiếu lại trong chuỗi phim kinh điển tại DUT Cinema, Metropolis mang đến cơ hội hiếm có để khán giả trẻ thưởng thức một tượng đài điện ảnh trên màn ảnh lớn. Những khung hình đại cảnh thành phố tầng trên và nhà máy ngầm bên dưới vẫn giữ nguyên sức nặng thị giác đáng kinh ngạc.",
        "Hải Đăng",
        "1 tuần trước",
        "metropolis",
        3190,
        3,
    ),
    (
        "blog-imax-guide",
        "blog",
        "Phòng chiếu IMAX tại DUT Sala khác gì so với phòng 2D thông thường?",
        "Tìm hiểu về kích thước màn hình cong tràn viền, máy chiếu laser kép và vị trí ghế vàng cho trải nghiệm điện ảnh tối ưu.",
        "Màn hình IMAX có tỉ lệ khung hình mở rộng lên đến 26% so với rạp thường, kết hợp hệ thống loa định hướng đa kênh được căn chỉnh riêng cho từng phòng chiếu. Với màn hình lớn, hàng ghế D (VIP) và hàng C giữa là vị trí lý tưởng nhất để bao quát toàn bộ khung hình mà không cần ngoái đầu.",
        "Ban Biên Tập DUT Cinema",
        "3 ngày trước",
        "orbit",
        7450,
        4,
    ),
    (
        "blog-classic-silent",
        "blog",
        "Vì sao phim hài hình thể của Charlie Chaplin và Buster Keaton vẫn gây cười sau 100 năm?",
        "Từ The Kid đến Sherlock Jr., nghệ thuật dàn dựng cú máy thật không kỹ xảo luôn có sức hấp dẫn bền bỉ.",
        "Không dựa vào lời thoại hay kỹ xảo CGI, thế hệ đạo diễn tiên phong như Charlie Chaplin và Buster Keaton biến chính cơ thể và bối cảnh thành chất liệu hài hước. Khi xem lại The Gold Rush hay The General trong rạp có khán giả cùng cười, trải nghiệm tập thể khiến những cảnh phim kinh điển trở nên sống động hơn bao giờ hết.",
        "Thảo Vy",
        "5 ngày trước",
        "the-kid",
        2890,
        5,
    ),
    (
        "blog-gstar-tips",
        "blog",
        "Bí kíp săn vé 50K và tích điểm D-Star nhanh nhất tại rạp",
        "Tổng hợp mẹo đặt vé ngày Happy Day, ưu đãi U22 và cách kết hợp combo bắp nước tiết kiệm tối đa.",
        "Để tối ưu chi phí đi xem phim hàng tuần, bạn nên đăng ký tài khoản thành viên trước khi đặt vé để mọi hóa đơn vé và bắp nước đều được cộng điểm Star tự động. Vào Thứ Hai đầu tiên hàng tháng, đừng quên kiểm tra lịch chiếu sớm và áp dụng mã ưu đãi trực tuyến.",
        "Ban Biên Tập DUT Cinema",
        "1 tuần trước",
        None,
        5120,
        6,
    ),
]

MOVIE_PROFILES = {
    "saigon": ("NOW_SHOWING", "T13", 9.1, "2026-11-12", "Nguyễn Quang Dũng", "Liên Bỉnh Phát, Kaity Nguyễn", "Việt Nam", "https://www.youtube.com/embed/dQw4w9WgXcQ", True),
    "orbit": ("NOW_SHOWING", "T16", 9.3, "2026-11-15", "Trần Anh Hùng", "Thuận Nguyễn, Phương Anh Đào", "Việt Nam · Nhật Bản", "https://www.youtube.com/embed/dQw4w9WgXcQ", True),
    "the-kid": ("NOW_SHOWING", "P", 9.0, "2026-10-20", "Charlie Chaplin", "Charlie Chaplin, Jackie Coogan", "Mỹ", "", False),
    "metropolis": ("NOW_SHOWING", "T13", 9.2, "2026-11-01", "Fritz Lang", "Brigitte Helm, Alfred Abel", "Đức", "", True),
    "the-general": ("NOW_SHOWING", "P", 8.8, "2026-11-02", "Buster Keaton", "Buster Keaton, Marion Mack", "Mỹ", "", False),
    "the-thief-of-bagdad": ("NOW_SHOWING", "P", 8.7, "2026-11-05", "Raoul Walsh", "Douglas Fairbanks, Anna May Wong", "Mỹ", "", True),
    "safety-last": ("NOW_SHOWING", "P", 8.6, "2026-11-06", "Fred C. Newmeyer", "Harold Lloyd, Mildred Davis", "Mỹ", "", False),
    "caligari": ("NOW_SHOWING", "T16", 8.9, "2026-10-30", "Robert Wiene", "Werner Krauss, Conrad Veidt", "Đức", "", False),
    "sunrise": ("NOW_SHOWING", "T13", 8.9, "2026-11-08", "F. W. Murnau", "George O'Brien, Janet Gaynor", "Mỹ", "", False),
    "gold-rush": ("NOW_SHOWING", "P", 9.0, "2026-11-09", "Charlie Chaplin", "Charlie Chaplin, Georgia Hale", "Mỹ", "", False),
    "wings": ("NOW_SHOWING", "T13", 8.8, "2026-11-10", "William A. Wellman", "Clara Bow, Charles Rogers", "Mỹ", "", True),
    "the-lodger": ("COMING_SOON", "T16", 8.5, "2026-12-05", "Alfred Hitchcock", "Ivor Novello, June Tripp", "Anh", "", False),
    "the-golem": ("COMING_SOON", "T16", 8.2, "2026-12-12", "Paul Wegener", "Paul Wegener, Albert Steinrück", "Đức", "", False),
    "prince-achmed": ("COMING_SOON", "P", 8.7, "2026-12-19", "Lotte Reiniger", "Phim hoạt hình cắt giấy kinh điển", "Đức", "", False),
    "gullivers-travels": ("COMING_SOON", "P", 8.1, "2026-12-25", "Dave Fleischer", "Jessica Dragonette, Lanny Ross", "Mỹ", "", False),
}


def migrate(connection):
    for path in sorted((ROOT / "migrations").glob("*.sql")):
        connection.execute(path.read_text(encoding="utf-8"), prepare=False)


def seed(connection):
    connection.execute(
        """
        INSERT INTO cinema_catalog.movies VALUES
            ('saigon', 'Sài Gòn Sau Mưa', 'Tâm lý · Tình cảm', 108,
             'Hai người lạ gặp nhau trong một đêm mưa và cùng lần theo những ký ức về thành phố.'),
            ('orbit', 'Quỹ Đạo Cuối', 'Khoa học viễn tưởng', 124,
             'Một đội kỹ sư phải tìm đường trở về khi trạm nghiên cứu đổi quỹ đạo.')
        ON CONFLICT (id) DO NOTHING;
        """,
        prepare=False,
    )

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.cinemas
                (id, name, city, address, hotline, formats, opening_hours, price_table)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                city = EXCLUDED.city,
                address = EXCLUDED.address,
                hotline = EXCLUDED.hotline,
                formats = EXCLUDED.formats,
                opening_hours = EXCLUDED.opening_hours,
                price_table = EXCLUDED.price_table
            """,
            [
                (cid, name, city, addr, hotline, fmts, hours, Jsonb(pt))
                for cid, name, city, addr, hotline, fmts, hours, pt in CINEMAS
            ],
        )
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.auditoriums (id, name) VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
            """,
            [(aid, name) for aid, name, _, _ in AUDITORIUMS],
        )
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.auditorium_cinemas (auditorium_id, cinema_id, screen_format)
            VALUES (%s, %s, %s)
            ON CONFLICT (auditorium_id) DO UPDATE SET
                cinema_id = EXCLUDED.cinema_id,
                screen_format = EXCLUDED.screen_format
            """,
            [(aid, cid, fmt) for aid, _, cid, fmt in AUDITORIUMS],
        )

    connection.execute(
        """
        INSERT INTO cinema_catalog.seats
        SELECT aud.id, row_name || seat_no,
               CASE WHEN row_name = 'D' THEN 'PREMIUM' ELSE 'STANDARD' END
        FROM cinema_catalog.auditoriums aud
        CROSS JOIN unnest(ARRAY['A', 'B', 'C', 'D']) AS rows(row_name)
        CROSS JOIN generate_series(1, 8) AS numbers(seat_no)
        ON CONFLICT DO NOTHING;

        INSERT INTO cinema_catalog.seats
        SELECT aud.id, 'E' || seat_no, 'COUPLE'
        FROM cinema_catalog.auditoriums aud
        CROSS JOIN generate_series(1, 4) AS numbers(seat_no)
        ON CONFLICT DO NOTHING;

        INSERT INTO cinema_catalog.screenings VALUES
            ('saigon-evening', 'saigon', 'room-1', date_trunc('minute', now()) + interval '1 day', 90000),
            ('saigon-imax', 'saigon', 'room-2', date_trunc('minute', now()) + interval '1 day 3 hours', 140000),
            ('orbit-evening', 'orbit', 'room-2', date_trunc('minute', now()) + interval '2 days', 140000),
            ('orbit-danang', 'orbit', 'room-3', date_trunc('minute', now()) + interval '2 days 4 hours', 85000),
            ('saigon-hanoi', 'saigon', 'room-4', date_trunc('minute', now()) + interval '1 day 6 hours', 85000)
        ON CONFLICT (id) DO NOTHING;

        INSERT INTO cinema_catalog.screening_details (screening_id, format, is_special) VALUES
            ('saigon-evening', '2D Phụ đề', false),
            ('saigon-imax', 'IMAX 2D', true),
            ('orbit-evening', 'IMAX 2D', true),
            ('orbit-danang', '2D Phụ đề', false),
            ('saigon-hanoi', '2D Lồng tiếng', false)
        ON CONFLICT (screening_id) DO NOTHING;
        """,
        prepare=False,
    )

    seed_theatrical_films(connection)
    seed_dut_content(connection)
    seed_admin_accounts(connection)


def seed_admin_accounts(connection):
    hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
    demo_accounts = [
        ("admin", "dut-cinema-admin-2026", "Quản trị viên DUT Cinema", "ADMIN"),
        ("staff", "dut-cinema-staff-2026", "Nhân viên Soát vé", "STAFF"),
    ]
    with connection.cursor() as cursor:
        for username, password, full_name, role in demo_accounts:
            cursor.execute(
                """
                INSERT INTO cinema_booking.accounts (id, username, password_hash, full_name, role)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (username) DO UPDATE SET
                    role = EXCLUDED.role,
                    full_name = COALESCE(cinema_booking.accounts.full_name, EXCLUDED.full_name)
                """,
                (uuid4(), username, hasher.hash(password), full_name, role),
            )


def seed_theatrical_films(connection):
    films = json.loads((ROOT / "cinema/demo_movies.json").read_text(encoding="utf-8"))
    now_showing_films = [f for f in films if MOVIE_PROFILES.get(f["id"], ("NOW_SHOWING",))[0] == "NOW_SHOWING"]
    first_showings = [(film["id"], "demo") for film in now_showing_films]
    reruns = [(film["id"], "rerun") for film in now_showing_films[:8]]
    room_cycle = [
        ("room-1", "2D Phụ đề", False),
        ("room-2", "IMAX 2D", True),
        ("room-3", "2D Phụ đề", False),
        ("room-4", "2D Lồng tiếng", False),
    ]
    screenings = []
    details = []
    for index, (movie_id, label) in enumerate(first_showings + reruns):
        day, slot = divmod(index, len(SHOW_TIMES))
        room_id, fmt, is_special = room_cycle[index % len(room_cycle)]
        if fmt == "IMAX 2D" and not MOVIE_PROFILES.get(movie_id, ("", "", 0, None, "", "", "", "", False))[8]:
            room_id, fmt, is_special = ("room-1", "2D Phụ đề", False)
        screening_id = f"{movie_id}-{label}"
        base_price = 140000 if fmt == "IMAX 2D" else 75000 + (slot % 3) * 10000
        screenings.append((screening_id, movie_id, room_id, 1 + (day % 6), SHOW_TIMES[slot], base_price))
        details.append((screening_id, fmt, is_special))

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.movies (id, title, genre, duration_minutes, synopsis)
            VALUES (%(id)s, %(title)s, %(genre)s, %(duration)s, %(synopsis)s)
            ON CONFLICT (id) DO NOTHING
            """,
            films,
        )
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.screenings (id, movie_id, auditorium_id, starts_at, base_price)
            VALUES (%s, %s, %s,
                ((now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date + %s + %s::time)
                    AT TIME ZONE 'Asia/Ho_Chi_Minh',
                %s)
            ON CONFLICT (id) DO NOTHING
            """,
            screenings,
        )
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.screening_details (screening_id, format, is_special)
            VALUES (%s, %s, %s)
            ON CONFLICT (screening_id) DO NOTHING
            """,
            details,
        )


def seed_dut_content(connection):
    films = json.loads((ROOT / "cinema/demo_movies.json").read_text(encoding="utf-8"))
    all_ids = ["saigon", "orbit"] + [f["id"] for f in films]
    profile_rows = []
    for index, movie_id in enumerate(all_ids):
        profile = MOVIE_PROFILES.get(movie_id)
        if profile:
            status, age, rating, rel_date, director, cast_list, country, trailer, is_imax = profile
        else:
            status = "NOW_SHOWING"
            age = ("P", "T13", "T16", "K")[index % 4]
            rating = round(8.2 + (index % 9) * 0.1, 1)
            rel_date = "2026-11-01"
            director = "Đạo diễn Kinh Điển"
            cast_list = "Dàn diễn viên điện ảnh kinh điển"
            country = "Quốc tế"
            trailer = ""
            is_imax = False
        profile_rows.append((movie_id, status, age, rating, rel_date, director, cast_list, country, trailer, is_imax))

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.movie_profiles
                (movie_id, release_status, age_rating, rating, release_date, director, cast_list,
                 country, trailer_url, is_imax)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (movie_id) DO UPDATE SET
                release_status = EXCLUDED.release_status,
                age_rating = EXCLUDED.age_rating,
                rating = EXCLUDED.rating,
                release_date = EXCLUDED.release_date,
                director = EXCLUDED.director,
                cast_list = EXCLUDED.cast_list,
                country = EXCLUDED.country,
                trailer_url = EXCLUDED.trailer_url,
                is_imax = EXCLUDED.is_imax
            """,
            profile_rows,
        )
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.concessions
                (id, name, description, price, category, badge, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                price = EXCLUDED.price,
                category = EXCLUDED.category,
                badge = EXCLUDED.badge,
                sort_order = EXCLUDED.sort_order
            """,
            CONCESSIONS,
        )
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.promotions
                (id, title, tag, summary, code, discount_type, discount_value, min_amount,
                 valid_until, details, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                tag = EXCLUDED.tag,
                summary = EXCLUDED.summary,
                code = EXCLUDED.code,
                discount_type = EXCLUDED.discount_type,
                discount_value = EXCLUDED.discount_value,
                min_amount = EXCLUDED.min_amount,
                valid_until = EXCLUDED.valid_until,
                details = EXCLUDED.details,
                sort_order = EXCLUDED.sort_order
            """,
            PROMOTIONS,
        )
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.blog_posts
                (id, category, title, summary, content, author, published_label, movie_id, views, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                category = EXCLUDED.category,
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                content = EXCLUDED.content,
                author = EXCLUDED.author,
                published_label = EXCLUDED.published_label,
                movie_id = EXCLUDED.movie_id,
                views = EXCLUDED.views,
                sort_order = EXCLUDED.sort_order
            """,
            BLOG_POSTS,
        )
    connection.execute(
        """
        DELETE FROM cinema_catalog.cinemas
        WHERE id IN ('galaxy-nguyen-du', 'galaxy-sala', 'galaxy-danang', 'galaxy-mipec');
        DELETE FROM cinema_catalog.promotions
        WHERE id IN ('promo-galaxy20', 'promo-gstar');
        """,
        prepare=False,
    )


def main():
    parser = argparse.ArgumentParser(description="Apply schemas to Supabase and optionally load demo data")
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--runtime-roles", nargs=3, metavar=("CATALOG", "BOOKING", "PAYMENT"))
    args = parser.parse_args()
    load_dotenv()
    if not (dsn := os.getenv("SUPABASE_DATABASE_URL")):
        parser.error("Set SUPABASE_DATABASE_URL in .env")
    with psycopg.connect(dsn, connect_timeout=8) as connection:
        migrate(connection)
        if args.seed:
            seed(connection)
        for schema, role in zip(SCHEMAS, args.runtime_roles or []):
            identifiers = {"schema": sql.Identifier(schema), "role": sql.Identifier(role)}
            connection.execute(sql.SQL("GRANT USAGE ON SCHEMA {schema} TO {role}").format(**identifiers))
            permissions = (
                "SELECT, INSERT, UPDATE, DELETE"
                if schema == "cinema_catalog"
                else "SELECT, INSERT, UPDATE"
            )
            connection.execute(
                sql.SQL("GRANT " + permissions + " ON ALL TABLES IN SCHEMA {schema} TO {role}").format(
                    **identifiers
                )
            )
            if schema == "cinema_booking":
                connection.execute(sql.SQL(
                    "GRANT DELETE ON cinema_booking.saved_bookings, cinema_booking.account_sessions, "
                    "cinema_booking.auth_attempts TO {role}"
                ).format(**identifiers))
    print("Đã áp dụng schema" + (" và nạp dữ liệu mẫu." if args.seed else "."))


if __name__ == "__main__":
    main()
