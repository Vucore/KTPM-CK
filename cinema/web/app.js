import { artwork, featuredMovies } from "./films/artwork.js?v=2";

const $ = (id) => document.getElementById(id);
const vietnamTime = { timeZone: "Asia/Ho_Chi_Minh" };
const formatDate = new Intl.DateTimeFormat("vi-VN", {
    ...vietnamTime, weekday: "long", day: "numeric", month: "numeric", year: "numeric",
});
const formatTime = new Intl.DateTimeFormat("vi-VN", {
    ...vietnamTime, hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
const formatShortDate = new Intl.DateTimeFormat("vi-VN", {
    ...vietnamTime, day: "2-digit", month: "2-digit", year: "numeric",
});
const formatPrice = new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" });
const seatOrder = new Intl.Collator("vi", { numeric: true });
const filmArt = new Map(artwork.flatMap((film) => [[film.id, film], [film.title, film]]));
const exampleFilms = new Set(["saigon", "orbit"]);

const paymentLabels = {
    PENDING: "Chưa thanh toán.",
    PROCESSING: "Đang chờ kết quả thanh toán…",
    DECLINED: "Thanh toán bị từ chối. Bạn có thể thử lại trong thời hạn giữ ghế.",
    SUCCEEDED: "Thanh toán thành công. Đang chờ xác nhận vé…",
    REFUNDED: "Đã hoàn tiền do đơn hết hạn.",
};
const bookingLabels = {
    HELD: "Chờ xác nhận",
    CONFIRMED: "Đã cấp vé",
    EXPIRED: "Hết hạn giữ ghế",
    CANCELLED: "Đã hủy giữ ghế",
};
const FOOTER_DOCS = {
    about: {
        tag: "Giới thiệu",
        title: "Về DUT Cinema",
        paragraphs: [
            "DUT Cinema là hệ thống rạp chiếu phim và nền tảng đặt vé trực tuyến hiện đại, kết nối lịch chiếu thời gian thực tại các cụm rạp trên toàn quốc.",
            "Khách hàng có thể tra cứu suất chiếu theo rạp, chọn ghế thường / VIP / Sweetbox, đặt kèm combo bắp nước, áp dụng mã ưu đãi và nhận vé điện tử QR ngay sau khi thanh toán.",
        ],
    },
    rules: {
        tag: "Quy chế rạp",
        title: "Quy chế hoạt động & Quy định vào rạp",
        paragraphs: [
            "1. Khán giả vui lòng có mặt trước giờ chiếu 15 phút để xuất trình mã vé QR tại cửa soát vé.",
            "2. Tuân thủ phân loại độ tuổi (P, K, T13, T16, T18) theo quy định hiện hành. Nhân viên rạp có quyền kiểm tra giấy tờ tùy thân khi cần thiết.",
            "3. Không mang đồ ăn, thức uống từ bên ngoài vào phòng chiếu và giữ im lặng trong suốt thời gian thưởng thức phim.",
        ],
    },
    privacy: {
        tag: "Bảo mật",
        title: "Chính sách bảo mật thông tin",
        paragraphs: [
            "Mật khẩu tài khoản thành viên được băm an toàn bằng Argon2id và phiên đăng nhập sử dụng cookie HttpOnly.",
            "Lịch sử đặt vé và điểm thưởng D-Star được đồng bộ theo tài khoản của bạn. Đơn đặt với tư cách khách được lưu riêng trên trình duyệt hiện tại.",
        ],
    },
    faq: {
        tag: "Hỗ trợ",
        title: "Câu hỏi thường gặp",
        paragraphs: [
            "• Thời gian giữ ghế là bao lâu? Mặc định hệ thống giữ ghế trong 5 phút để bạn hoàn tất thanh toán.",
            "• Thanh toán trễ sau khi hết hạn giữ ghế thì sao? Hệ thống tự động kiểm tra theo thời gian máy chủ và hoàn tiền ngay nếu bạn đã thanh toán thành công sau thời hạn.",
            "• Làm sao xem lại vé đã mua? Mở mục Vé của tôi trên thanh điều hướng hoặc dán mã đơn / mã vé để tra cứu.",
        ],
    },
};

const page = new URLSearchParams(location.search);
const currentView = page.get("view") || "";
const signingUp = page.get("mode") === "register";
const accountUpdates = "BroadcastChannel" in window ? new BroadcastChannel("chon-suat.account") : null;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

let catalogData = { screenings: [], coming_soon: [], cinemas: [], concessions: [], promotions: [], blog_posts: [] };
let movies = [];
let comingSoonMovies = [];
let activeMovieTab = "now";
let featured = [];
let featuredIndex = 0;
let featuredPlaying = !reducedMotion.matches;
let featuredTimer = null;

let currentAccount = null;
let activeMovieDetail = null;
let activeCinemaId = null;
let activeCinemaCity = "Tất cả";
let activeBlogCat = "all";

let screening = null;
let seatList = [];
let seatOrigin = null;
let selected = new Set();
let concessionQty = new Map();
let appliedPromoCode = "";
let redeemedPoints = 0;
let seatRefresh = null;
let seatEvents = null;
let seatRequest = 0;
let seatSignature = null;
let checkoutBusy = false;
let paymentBusy = false;
let paymentRevision = 0;
let booking = null;
let clockOffset = 0;
let payment = null;
let bookingId = page.get("booking");
let loadingOrder = false;
let missingOrder = false;
let shownTickets = "";
let modalOrigin = null;

function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
}

function setText(id, text) {
    const node = $(id);
    if (node && node.textContent !== text) node.textContent = text;
}

function notice(text = "") {
    $("notice").hidden = !text;
    setText("notice", text);
}

function report(id, message = "", state = "") {
    const node = $(id);
    if (!node) return;
    node.hidden = !message;
    node.dataset.state = state;
    setText(id, message);
}

function showStage(step) {
    for (const id of ["step-seats", "step-concessions", "step-payment", "step-tickets"]) {
        if (id === step) $(id).setAttribute("aria-current", "step");
        else $(id).removeAttribute("aria-current");
    }
}

function show(view) {
    const sections = [
        "catalog", "movie-detail", "cinemas-view", "promotions-view",
        "blog-view", "seating", "concessions-step", "order", "my-tickets", "account", "admin-view",
    ];
    for (const id of sections) $(id).hidden = id !== view;
    const inBooking = view === "seating" || view === "concessions-step" || view === "order";
    $("booking-flow").hidden = !inBooking;
    syncFeaturedMotion();

    const navMap = {
        "nav-movies": view === "catalog" || view === "movie-detail",
        "nav-blog": view === "blog-view",
        "nav-promotions": view === "promotions-view",
        "nav-cinemas": view === "cinemas-view",
        "ticket-history-link": view === "my-tickets",
        "account-link": view === "account",
        "admin-nav-link": view === "admin-view",
    };
    for (const [id, active] of Object.entries(navMap)) {
        const node = $(id);
        if (!node) continue;
        if (active) node.setAttribute("aria-current", "page");
        else node.removeAttribute("aria-current");
    }
    if (view === "seating") showStage("step-seats");
    if (view === "concessions-step") showStage("step-concessions");
    if (view === "order") showStage("step-payment");
}

async function api(path, options) {
    let response;
    try {
        response = await fetch(path, { ...options, cache: "no-store" });
    } catch {
        throw new Error("Mất kết nối. Hãy thử lại.");
    }
    if (response.status === 204) return null;
    const data = await response.json().catch(() => null);
    if (!response.ok) {
        const message = typeof data?.detail === "string" ? data.detail : "Không thể hoàn tất yêu cầu.";
        throw Object.assign(new Error(message), { status: response.status });
    }
    return data;
}

function post(path, input, key) {
    const headers = { "Content-Type": "application/json" };
    if (key) headers["Idempotency-Key"] = key;
    return api(path, { method: "POST", headers, body: JSON.stringify(input) });
}

function requestKey(slot, payload) {
    const fingerprint = JSON.stringify(payload);
    const saved = JSON.parse(sessionStorage.getItem(slot) || "null");
    if (saved?.fingerprint === fingerprint) return saved.key;
    const key = crypto.randomUUID();
    sessionStorage.setItem(slot, JSON.stringify({ fingerprint, key }));
    return key;
}

function shortTime(startsAt) {
    return formatTime.format(new Date(startsAt));
}

function dateLabel(startsAt) {
    const date = formatDate.format(new Date(startsAt));
    return date.charAt(0).toLocaleUpperCase("vi-VN") + date.slice(1);
}

function isWeekendVN(startsAt) {
    const weekday = new Intl.DateTimeFormat("en-US", { ...vietnamTime, weekday: "short" }).format(new Date(startsAt));
    return weekday === "Sat" || weekday === "Sun";
}

function seatUnitPrice(basePrice, seatType, startsAt) {
    const standard = basePrice + (isWeekendVN(startsAt) ? 15000 : 0);
    if (seatType === "COUPLE") return standard * 2 + 15000;
    if (seatType === "PREMIUM") return standard + 20000;
    return standard;
}

function screeningLabel(slot) {
    return `${shortTime(slot.starts_at)} · ${dateLabel(slot.starts_at)} · ${slot.auditorium}`;
}

function orderUrl(id) {
    return `/?booking=${encodeURIComponent(id)}`;
}

function searchText(value) {
    return (value || "").toLocaleLowerCase("vi-VN").normalize("NFD").replace(/\p{M}/gu, "").replaceAll("đ", "d").trim();
}

function option(value, label) {
    return new Option(label, value);
}

function posterUrl(movieKey, customUrl = "") {
    if (customUrl) return customUrl;
    const art = filmArt.get(movieKey);
    return art ? `/assets/films/${art.poster}` : "";
}

function openModal({ tag = "", title, bodyNodes, origin }) {
    modalOrigin = origin || document.activeElement;
    const tagNode = $("modal-tag");
    tagNode.hidden = !tag;
    tagNode.textContent = tag;
    setText("modal-title", title);
    $("modal-body").replaceChildren(...bodyNodes);
    $("app-modal").hidden = false;
    $("modal-close").focus();
}

function closeModal() {
    if ($("app-modal").hidden) return;
    $("app-modal").hidden = true;
    $("modal-body").replaceChildren();
    modalOrigin?.focus?.();
}

$("modal-close").addEventListener("click", closeModal);
$("app-modal").addEventListener("click", (event) => {
    if (event.target === $("app-modal")) closeModal();
});
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeModal();
});

function openTrailerModal(movie, origin) {
    const nodes = [];
    if (movie.trailer_url) {
        const frame = element("iframe", null, "trailer-frame");
        frame.src = movie.trailer_url;
        frame.title = `Trailer ${movie.title}`;
        frame.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture";
        frame.allowFullscreen = true;
        nodes.push(frame);
    } else {
        nodes.push(element("p", "Phim kinh điển hiện chưa có video trailer nhúng trực tuyến. Bạn có thể xem tóm tắt nội dung bên dưới."));
    }
    if (movie.synopsis) nodes.push(element("p", movie.synopsis));
    const btn = element("a", "Xem chi tiết & Lịch chiếu", "button primary");
    btn.href = `/?view=movie&id=${encodeURIComponent(movie.key || movie.id)}`;
    nodes.push(btn);
    openModal({ tag: movie.age_rating || "Trailer", title: `Trailer: ${movie.title}`, bodyNodes: nodes, origin });
}

function openInfoModal(docKey, origin) {
    const doc = FOOTER_DOCS[docKey];
    if (!doc) return;
    openModal({
        tag: doc.tag,
        title: doc.title,
        bodyNodes: doc.paragraphs.map((p) => element("p", p)),
        origin,
    });
}

document.querySelectorAll(".footer-link-btn").forEach((btn) => {
    btn.addEventListener("click", () => openInfoModal(btn.dataset.info, btn));
});

$("mobile-menu-toggle").addEventListener("click", () => {
    const drawer = $("mobile-drawer");
    const open = drawer.hidden;
    drawer.hidden = !open;
    $("mobile-menu-toggle").setAttribute("aria-expanded", String(open));
});

/* ---------------- HOME & CATALOG ---------------- */
function groupMovies(screenings) {
    const groups = new Map();
    for (const slot of screenings) {
        const key = slot.movie_id ?? JSON.stringify([slot.title, slot.genre, slot.duration_minutes]);
        if (!groups.has(key)) {
            groups.set(key, {
                key,
                id: slot.movie_id ?? key,
                title: slot.title,
                genre: slot.genre,
                duration: slot.duration_minutes,
                synopsis: slot.synopsis,
                age_rating: slot.age_rating || "P",
                rating: slot.rating || 8.5,
                is_imax: Boolean(slot.is_imax),
                director: slot.director || "",
                cast_list: slot.cast_list || "",
                country: slot.country || "Việt Nam",
                trailer_url: slot.trailer_url || "",
                poster_url: slot.poster_url || "",
                release_date: slot.release_date || null,
                art: filmArt.get(slot.movie_id ?? slot.title),
                screenings: [],
            });
        }
        groups.get(key).screenings.push(slot);
    }
    return [...groups.values()].sort((first, second) =>
        Number(exampleFilms.has(first.art?.id)) - Number(exampleFilms.has(second.art?.id)));
}

function renderFeatured() {
    const film = featured[featuredIndex];
    const visual = $("featured-visual");
    visual.replaceChildren();
    visual.classList.toggle("hero-portrait", Boolean(film.art && !film.art.banner));
    visual.style.removeProperty("--featured-image");
    if (film.art) {
        const art = element("img", null, "hero-art");
        art.id = "featured-art";
        art.alt = "";
        art.fetchPriority = "high";
        art.dataset.film = film.art.id;
        const image = `/assets/films/${film.art.banner || film.art.poster}`;
        if (film.art.banner) art.srcset = `/assets/films/${film.art.poster} 720w, ${image} 1720w`;
        else visual.style.setProperty("--featured-image", `url("${image}")`);
        art.addEventListener("error", () => art.remove(), { once: true });
        art.src = image;
        visual.append(art);
    }
    const badges = [element("span", film.age_rating, "age-badge")];
    badges[0].dataset.age = film.age_rating;
    if (film.is_imax) badges.push(element("span", "IMAX", "format-badge"));
    badges.push(element("span", `★ ${Number(film.rating).toFixed(1)}`, "rating-pill"));
    $("featured-badges").replaceChildren(...badges);
    setText("featured-title", film.title);
    setText("featured-meta", `${film.genre} · ${film.duration} phút`);

    const canBrowse = featured.length > 1;
    $("featured-controls").hidden = !canBrowse;
    $("featured-pagination").hidden = !canBrowse;
    if (canBrowse) {
        for (const [index, dot] of Array.from($("featured-dots").children).entries()) {
            if (index === featuredIndex) dot.setAttribute("aria-current", "true");
            else dot.removeAttribute("aria-current");
        }
        renderFeaturedPreview("previous-preview", -1);
        renderFeaturedPreview("next-preview", 1);
    } else {
        $("previous-preview").hidden = true;
        $("next-preview").hidden = true;
    }
    $("featured").hidden = false;
}

function renderFeaturedPreview(id, offset) {
    const preview = $(id);
    const { art } = featured[(featuredIndex + offset + featured.length) % featured.length];
    preview.replaceChildren();
    preview.hidden = !art;
    if (!art) return;
    const image = element("img");
    image.alt = "";
    image.src = `/assets/films/${art.poster}`;
    image.addEventListener("error", () => image.remove(), { once: true });
    preview.append(image);
}

function setupFeaturedDots() {
    $("featured-dots").replaceChildren(...featured.map((film, index) => {
        const dot = element("button", null, "hero-dot");
        dot.type = "button";
        dot.setAttribute("aria-label", `Banner ${index + 1}: ${film.title}`);
        dot.addEventListener("click", () => {
            setFeaturedPlaying(false);
            featuredIndex = index;
            renderFeatured();
        });
        return dot;
    }));
}

function moveFeatured(offset) {
    featuredIndex = (featuredIndex + offset + featured.length) % featured.length;
    renderFeatured();
}

function setFeaturedPlaying(playing) {
    featuredPlaying = playing;
    syncFeaturedMotion();
}

function syncFeaturedMotion() {
    clearInterval(featuredTimer);
    setText("featured-motion", featuredPlaying ? "Tạm dừng" : "Phát banner");
    $("featured-copy").setAttribute("aria-live", featuredPlaying ? "off" : "polite");
    if (!featuredPlaying || featured.length < 2 || $("catalog").hidden || document.hidden) return;
    featuredTimer = setInterval(() => {
        if (!$("featured").matches(":hover")) moveFeatured(1);
    }, 7000);
}

/* QUICK BOOK BAR */
function setQuickOptions(id, placeholder, options) {
    const select = $(id);
    select.replaceChildren(option("", placeholder), ...options);
    select.disabled = options.length === 0;
}

function quickFilmScreenings() {
    return movies.find((movie) => movie.key === $("quick-film").value)?.screenings ?? [];
}

function cinemaKey(slot) {
    return slot.cinema_id || slot.auditorium_id || slot.auditorium;
}

function quickCinemaScreenings() {
    return quickFilmScreenings().filter((slot) => cinemaKey(slot) === $("quick-room").value);
}

function updateQuickRooms() {
    const cinemas = new Map(quickFilmScreenings().map((slot) => [
        cinemaKey(slot),
        slot.cinema_name ? `${slot.cinema_name} (${slot.city})` : slot.auditorium,
    ]));
    setQuickOptions("quick-room", "Chọn Rạp", [...cinemas].map(([key, label]) => option(key, label)));
    if (cinemas.size === 1) $("quick-room").selectedIndex = 1;
    updateQuickDates();
}

function updateQuickDates() {
    const dates = new Map(quickCinemaScreenings().map((slot) => [
        dateLabel(slot.starts_at), formatShortDate.format(new Date(slot.starts_at)),
    ]));
    setQuickOptions("quick-date", "Chọn Ngày", [...dates].map(([key, label]) => option(key, label)));
    if (dates.size === 1) $("quick-date").selectedIndex = 1;
    updateQuickScreenings();
}

function updateQuickScreenings() {
    const slots = quickCinemaScreenings().filter((slot) => dateLabel(slot.starts_at) === $("quick-date").value);
    setQuickOptions(
        "quick-screening",
        "Chọn Suất",
        slots.map((slot) => option(slot.id, `${shortTime(slot.starts_at)} · ${slot.format || "2D"}`)),
    );
    updateQuickSubmit();
}

function updateQuickSubmit() {
    $("quick-submit").disabled = !$("quick-screening").value;
}

function movieCard(movie, screenings, comingSoon = false) {
    const card = element("article", null, "movie-card");
    const poster = element("div", null, "poster");
    poster.append(element("span", null, "brand-mark"));
    const art = movie.art || filmArt.get(movie.id ?? movie.title);
    const customSrc = posterUrl(movie.id ?? movie.title, movie.poster_url);
    if (art || customSrc) {
        const img = element("img");
        img.alt = `Poster phim ${movie.title}`;
        img.loading = "lazy";
        img.decoding = "async";
        if (art) {
            img.dataset.film = art.id;
            img.classList.toggle("still", Boolean(art.banner));
        }
        img.addEventListener("error", () => img.remove(), { once: true });
        img.src = customSrc;
        poster.append(img);
    }

    if (movie.is_imax) poster.append(element("span", "IMAX", "imax-tag"));

    const badges = element("div", null, "poster-badges");
    badges.append(element("span", `★ ${Number(movie.rating || 8.5).toFixed(1)}`, "rating-pill"));
    const age = element("span", movie.age_rating || "P", "age-badge");
    age.dataset.age = movie.age_rating || "P";
    badges.append(age);
    poster.append(badges);

    const overlay = element("div", null, "poster-overlay");
    const buyBtn = element("a", comingSoon ? "Chi tiết phim" : "Mua vé", "button primary");
    buyBtn.href = `/?view=movie&id=${encodeURIComponent(movie.id)}`;
    const trailerBtn = element("button", "Trailer", "button btn-trailer");
    trailerBtn.type = "button";
    trailerBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        openTrailerModal(movie, trailerBtn);
    });
    overlay.append(buyBtn, trailerBtn);
    poster.append(overlay);

    const info = element("div", null, "movie-info");
    const titleBtn = element("a", movie.title, "movie-title-link");
    titleBtn.href = `/?view=movie&id=${encodeURIComponent(movie.id)}`;

    info.append(
        titleBtn,
        element("p", `${movie.genre} · ${movie.duration || movie.duration_minutes} phút`, "movie-meta"),
    );

    if (comingSoon) {
        const releaseText = movie.release_date
            ? `Khởi chiếu: ${formatShortDate.format(new Date(movie.release_date))}`
            : "Sắp khởi chiếu";
        info.append(element("p", releaseText, "soon-release"));
    } else {
        const schedule = element("div", null, "showtimes");
        const days = new Map();
        for (const slot of screenings.slice(0, 6)) {
            const day = formatShortDate.format(new Date(slot.starts_at));
            if (!days.has(day)) {
                const group = element("div");
                const times = element("div", null, "showtime-list");
                group.append(element("p", `${day} · ${slot.cinema_name || slot.auditorium}`, "showtime-day"), times);
                schedule.append(group);
                days.set(day, times);
            }
            const button = element("button", `${shortTime(slot.starts_at)} · ${slot.format || "2D"}`, "showtime");
            button.type = "button";
            button.setAttribute("aria-label", `Chọn ghế cho ${movie.title}, ${screeningLabel(slot)}`);
            button.addEventListener("click", () => openScreening(slot, button));
            days.get(day).append(button);
        }
        info.append(schedule);
    }

    card.append(poster, info);
    return card;
}

function renderSchedule() {
    const city = $("schedule-city").value;
    const date = $("schedule-date").value;
    const query = searchText($("movie-search").value);
    const cards = [];

    if (activeMovieTab === "soon") {
        for (const film of comingSoonMovies) {
            if (query && !searchText(film.title).includes(query)) continue;
            cards.push(movieCard(film, [], true));
        }
        $("screenings").replaceChildren(...cards);
        setText("movie-count", `${cards.length} phim sắp chiếu`);
        $("catalog-state").hidden = cards.length > 0;
        if (!cards.length) setText("catalog-state", "Chưa có phim sắp chiếu phù hợp.");
        return;
    }

    for (const film of movies) {
        if (activeMovieTab === "imax" && !film.is_imax) continue;
        if (query && !searchText(film.title).includes(query)) continue;
        let slots = film.screenings;
        if (city) slots = slots.filter((slot) => slot.city === city);
        if (date) slots = slots.filter((slot) => dateLabel(slot.starts_at) === date);
        if (activeMovieTab === "imax") {
            const imaxSlots = slots.filter((slot) => (slot.format || "").includes("IMAX"));
            if (imaxSlots.length) slots = imaxSlots;
        }
        if (slots.length) cards.push(movieCard(film, slots, false));
    }

    $("screenings").replaceChildren(...cards);
    setText("movie-count", `${cards.length} phim`);
    $("catalog-state").hidden = cards.length > 0 || !movies.length;
    if (!cards.length && movies.length) {
        setText("catalog-state", "Không tìm thấy phim phù hợp. Hãy đổi khu vực, tên phim hoặc ngày chiếu.");
    }
}

function renderHomeSpotlight() {
    const posts = (catalogData.blog_posts || []).slice(0, 3);
    const promos = (catalogData.promotions || []).slice(0, 4);
    if (!posts.length && !promos.length) {
        $("home-spotlight").hidden = true;
        return;
    }
    $("home-blog-list").replaceChildren(...posts.map((post) => {
        const card = element("button", null, "spotlight-item");
        card.type = "button";
        card.append(
            element("span", post.category === "review" ? "Bình luận phim" : "Blog điện ảnh", "promo-tag"),
            element("h4", post.title),
            element("p", `${post.author} · ${post.published_label} · ${post.views.toLocaleString("vi-VN")} lượt xem`),
        );
        card.addEventListener("click", () => openBlogModal(post, card));
        return card;
    }));
    $("home-promo-list").replaceChildren(...promos.map((promo) => {
        const card = element("button", null, "spotlight-promo");
        card.type = "button";
        card.append(
            element("span", promo.tag, "promo-tag"),
            element("h4", promo.title),
        );
        card.addEventListener("click", () => openPromoModal(promo, card));
        return card;
    }));
    $("home-spotlight").hidden = false;
}

async function ensureCatalogData() {
    if (catalogData.screenings.length || catalogData.cinemas.length) return catalogData;
    try {
        catalogData = await api("/api/catalog/home");
    } catch {
        const screenings = await api("/api/screenings");
        catalogData = { ...catalogData, screenings };
    }
    movies = groupMovies(catalogData.screenings || []);
    comingSoonMovies = (catalogData.coming_soon || []).map((m) => ({
        ...m,
        key: m.id,
        art: filmArt.get(m.id ?? m.title),
    }));
    return catalogData;
}

async function loadCatalog() {
    $("reload-catalog").hidden = true;
    $("catalog-state").hidden = false;
    setText("catalog-state", "Đang tải lịch chiếu…");
    try {
        catalogData = await api("/api/catalog/home").catch(async () => ({
            ...catalogData,
            screenings: await api("/api/screenings"),
        }));
        const screenings = catalogData.screenings || [];
        movies = groupMovies(screenings);
        comingSoonMovies = (catalogData.coming_soon || []).map((m) => ({
            ...m,
            key: m.id,
            art: filmArt.get(m.id ?? m.title),
        }));

        const cities = [...new Set(screenings.map((slot) => slot.city).filter(Boolean))];
        $("schedule-city").replaceChildren(option("", "Toàn quốc"), ...cities.map((c) => option(c, c)));

        const dates = new Map(screenings.map((slot) => [
            dateLabel(slot.starts_at), formatShortDate.format(new Date(slot.starts_at)),
        ]));
        $("schedule-filters").hidden = !movies.length;
        $("date-filter").hidden = dates.size < 2;
        $("movie-search").value = "";
        $("schedule-date").replaceChildren(option("", "Tất cả ngày"), ...[...dates].map(([key, label]) => option(key, label)));

        renderSchedule();
        renderHomeSpotlight();
        $("movie-count").hidden = !movies.length;
        $("dat-ve").hidden = !movies.length;
        if (!movies.length) {
            setText("catalog-state", "Hiện chưa có suất chiếu sắp tới.");
            $("catalog-state").hidden = false;
            $("featured").hidden = true;
            featured = [];
            syncFeaturedMotion();
            return;
        }
        featured = featuredMovies.map((id) => movies.find((movie) => movie.art?.id === id)).filter(Boolean);
        if (!featured.length) featured = movies.slice(0, 6);
        featuredIndex = 0;
        setupFeaturedDots();
        renderFeatured();
        syncFeaturedMotion();
        setQuickOptions("quick-film", "Chọn Phim", movies.map((movie) => option(movie.key, movie.title)));
        updateQuickRooms();
        $("catalog-state").hidden = true;
    } catch (error) {
        setText("catalog-state", error.message);
        $("reload-catalog").hidden = false;
    }
    if (location.hash === "#lich-chieu") $("lich-chieu").scrollIntoView();
}

document.querySelectorAll(".movie-tabs[aria-label='Danh mục phim'] .movie-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
        activeMovieTab = tab.dataset.tab;
        document.querySelectorAll(".movie-tabs[aria-label='Danh mục phim'] .movie-tab").forEach((btn) => {
            btn.setAttribute("aria-selected", String(btn === tab));
        });
        $("date-filter").hidden = activeMovieTab === "soon";
        $("schedule-city").hidden = activeMovieTab === "soon";
        renderSchedule();
    });
});

$("previous-film").addEventListener("click", () => { setFeaturedPlaying(false); moveFeatured(-1); });
$("next-film").addEventListener("click", () => { setFeaturedPlaying(false); moveFeatured(1); });
$("featured-motion").addEventListener("click", () => setFeaturedPlaying(!featuredPlaying));
$("featured").addEventListener("focusin", (event) => {
    if (event.target !== $("featured-motion")) setFeaturedPlaying(false);
});
document.addEventListener("visibilitychange", syncFeaturedMotion);
reducedMotion.addEventListener("change", () => setFeaturedPlaying(!reducedMotion.matches));

$("featured-book").addEventListener("click", () => {
    $("quick-film").value = featured[featuredIndex].key;
    updateQuickRooms();
    $("dat-ve").scrollIntoView();
    const nextField = $("quick-room").value ? $("quick-date") : $("quick-room");
    nextField.focus({ preventScroll: true });
});
$("featured-detail").addEventListener("click", () => {
    const film = featured[featuredIndex];
    if (film) location.href = `/?view=movie&id=${encodeURIComponent(film.id)}`;
});

$("quick-film").addEventListener("change", updateQuickRooms);
$("quick-room").addEventListener("change", updateQuickDates);
$("quick-date").addEventListener("change", updateQuickScreenings);
$("quick-screening").addEventListener("change", updateQuickSubmit);
$("schedule-city").addEventListener("change", renderSchedule);
$("schedule-date").addEventListener("change", renderSchedule);
$("movie-search").addEventListener("input", renderSchedule);
$("dat-ve").addEventListener("submit", (event) => {
    event.preventDefault();
    const slot = quickCinemaScreenings().find((item) => item.id === $("quick-screening").value);
    if (slot) openScreening(slot, event.submitter || $("quick-screening"));
});
$("reload-catalog").addEventListener("click", loadCatalog);

/* ---------------- MOVIE DETAIL ---------------- */
function renderDetailShowtimes() {
    if (!activeMovieDetail) return;
    const city = $("detail-city").value;
    const date = $("detail-date").value;
    let slots = activeMovieDetail.screenings || [];
    if (city) slots = slots.filter((s) => s.city === city);
    if (date) slots = slots.filter((s) => dateLabel(s.starts_at) === date);

    const byCinema = new Map();
    for (const slot of slots) {
        const cname = slot.cinema_name || slot.auditorium;
        if (!byCinema.has(cname)) byCinema.set(cname, { city: slot.city || "", formats: new Map() });
        const fmt = slot.format || "2D Phụ đề";
        if (!byCinema.get(cname).formats.has(fmt)) byCinema.get(cname).formats.set(fmt, []);
        byCinema.get(cname).formats.get(fmt).push(slot);
    }

    const cards = [];
    for (const [cinemaName, info] of byCinema) {
        const card = element("article", null, "cinema-schedule-card");
        const head = element("div", null, "cinema-schedule-head");
        head.append(element("h3", cinemaName), element("span", info.city, "muted"));
        card.append(head);
        for (const [fmt, fmtSlots] of info.formats) {
            const row = element("div", null, "format-row");
            row.append(element("span", fmt, "format-row-label"));
            const list = element("div", null, "showtime-list");
            for (const slot of fmtSlots) {
                const btn = element("button", `${shortTime(slot.starts_at)} · ${formatShortDate.format(new Date(slot.starts_at))}`, "showtime");
                btn.type = "button";
                btn.addEventListener("click", () => openScreening(slot, btn));
                list.append(btn);
            }
            row.append(list);
            card.append(row);
        }
        cards.push(card);
    }
    $("detail-cinema-list").replaceChildren(...cards);
    $("detail-showtimes-empty").hidden = cards.length > 0;
}

async function loadMovieDetail(movieId) {
    show("movie-detail");
    $("detail-content").hidden = true;
    report("detail-status", "Đang tải thông tin phim…");
    try {
        await ensureCatalogData();
        const movie = await api(`/api/movies/${encodeURIComponent(movieId)}`);
        activeMovieDetail = movie;
        const poster = $("detail-poster");
        poster.replaceChildren();
        const src = posterUrl(movie.id ?? movie.title, movie.poster_url);
        if (src) {
            const img = element("img");
            img.alt = `Poster ${movie.title}`;
            img.src = src;
            poster.append(img);
        }

        const badges = [element("span", movie.age_rating || "P", "age-badge")];
        badges[0].dataset.age = movie.age_rating || "P";
        if (movie.is_imax) badges.push(element("span", "IMAX", "format-badge"));
        badges.push(element("span", `★ ${Number(movie.rating || 8.5).toFixed(1)}`, "rating-pill"));
        $("detail-badges").replaceChildren(...badges);

        setText("detail-title", movie.title);
        setText("detail-meta", `${movie.genre} · ${movie.duration_minutes} phút`);
        setText("detail-synopsis", movie.synopsis || "Chưa có mô tả chi tiết.");

        const facts = [
            ["Quốc gia", movie.country || "Quốc tế"],
            ["Khởi chiếu", movie.release_date ? formatShortDate.format(new Date(movie.release_date)) : "Đang chiếu"],
            ["Đạo diễn", movie.director || "Đang cập nhật"],
            ["Diễn viên", movie.cast_list || "Đang cập nhật"],
        ];
        $("detail-facts").replaceChildren(...facts.map(([k, v]) => {
            const row = element("div");
            row.append(element("dt", `${k}:`), element("dd", v));
            return row;
        }));

        const trailerBtn = $("detail-trailer-btn");
        trailerBtn.hidden = false;
        trailerBtn.onclick = () => openTrailerModal(movie, trailerBtn);

        const cities = [...new Set((movie.screenings || []).map((s) => s.city).filter(Boolean))];
        $("detail-city").replaceChildren(option("", "Toàn quốc"), ...cities.map((c) => option(c, c)));
        const dates = new Map((movie.screenings || []).map((s) => [
            dateLabel(s.starts_at), formatShortDate.format(new Date(s.starts_at)),
        ]));
        $("detail-date").replaceChildren(option("", "Tất cả ngày"), ...[...dates].map(([k, v]) => option(k, v)));

        renderDetailShowtimes();
        report("detail-status");
        $("detail-content").hidden = false;
    } catch (error) {
        report("detail-status", error.message, "ERROR");
    }
}

$("detail-city").addEventListener("change", renderDetailShowtimes);
$("detail-date").addEventListener("change", renderDetailShowtimes);
$("detail-back").addEventListener("click", () => { location.href = "/"; });

/* ---------------- CINEMAS & PRICING ---------------- */
function selectCinema(cinemaId) {
    activeCinemaId = cinemaId;
    const cinema = (catalogData.cinemas || []).find((c) => c.id === cinemaId);
    if (!cinema) return;

    document.querySelectorAll("#cinema-cards .cinema-card").forEach((card) => {
        if (card.dataset.cinemaId === cinemaId) card.setAttribute("aria-current", "true");
        else card.removeAttribute("aria-current");
    });

    setText("cinema-detail-name", cinema.name);
    setText("cinema-detail-address", `${cinema.address} · Hotline: ${cinema.hotline} · Mở cửa: ${cinema.opening_hours}`);
    $("cinema-detail-meta").replaceChildren(...(cinema.formats || []).map((fmt) => element("span", fmt, "format-badge")));

    $("cinema-price-body").replaceChildren(...(cinema.price_table || []).map((row) => {
        const tr = element("tr");
        tr.append(
            element("td", row.label),
            element("td", row.standard),
            element("td", row.vip),
            element("td", row.couple),
        );
        return tr;
    }));

    const cinemaScreenings = (catalogData.screenings || []).filter((s) => s.cinema_id === cinema.id);
    const byMovie = new Map();
    for (const slot of cinemaScreenings) {
        if (!byMovie.has(slot.movie_id)) byMovie.set(slot.movie_id, { title: slot.title, slots: [] });
        byMovie.get(slot.movie_id).slots.push(slot);
    }
    const showtimeNodes = [];
    for (const [, info] of byMovie) {
        const box = element("div", null, "cinema-movie-row");
        box.append(element("h4", info.title));
        const list = element("div", null, "showtime-list");
        for (const slot of info.slots.slice(0, 8)) {
            const btn = element("button", `${shortTime(slot.starts_at)} · ${formatShortDate.format(new Date(slot.starts_at))} · ${slot.format || "2D"}`, "showtime");
            btn.type = "button";
            btn.addEventListener("click", () => openScreening(slot, btn));
            list.append(btn);
        }
        box.append(list);
        showtimeNodes.push(box);
    }
    $("cinema-showtimes-list").replaceChildren(...(showtimeNodes.length
        ? showtimeNodes
        : [element("p", "Hiện chưa có suất chiếu sắp tới tại rạp này.", "muted")]));
    $("cinema-detail-panel").hidden = false;
}

function renderCinemaCards() {
    const cinemas = (catalogData.cinemas || []).filter(
        (c) => activeCinemaCity === "Tất cả" || c.city === activeCinemaCity,
    );
    $("cinema-cards").replaceChildren(...cinemas.map((cinema) => {
        const card = element("button", null, "cinema-card");
        card.type = "button";
        card.dataset.cinemaId = cinema.id;
        card.append(
            element("h3", cinema.name),
            element("p", `${cinema.city} · ${cinema.address}`),
            element("p", `Định dạng: ${(cinema.formats || []).join(", ")}`),
        );
        card.addEventListener("click", () => selectCinema(cinema.id));
        return card;
    }));
    if (cinemas.length) {
        const target = cinemas.some((c) => c.id === activeCinemaId) ? activeCinemaId : cinemas[0].id;
        selectCinema(target);
    } else {
        $("cinema-detail-panel").hidden = true;
    }
}

async function loadCinemasView() {
    show("cinemas-view");
    await ensureCatalogData();
    const cities = ["Tất cả", ...new Set((catalogData.cinemas || []).map((c) => c.city))];
    $("cinema-city-tabs").replaceChildren(...cities.map((city) => {
        const pill = element("button", city, "city-pill");
        pill.type = "button";
        pill.setAttribute("aria-selected", String(city === activeCinemaCity));
        pill.addEventListener("click", () => {
            activeCinemaCity = city;
            document.querySelectorAll("#cinema-city-tabs .city-pill").forEach((b) => {
                b.setAttribute("aria-selected", String(b === pill));
            });
            renderCinemaCards();
        });
        return pill;
    }));
    renderCinemaCards();
}

/* ---------------- PROMOTIONS & BLOG ---------------- */
function openPromoModal(promo, origin) {
    const nodes = [
        element("p", promo.summary),
        element("p", promo.details),
        element("p", `Thời gian áp dụng: ${promo.valid_until}`, "muted"),
    ];
    if (promo.code) {
        const row = element("div", null, "promo-code-row");
        row.append(element("span", "Mã ưu đãi:"), element("code", promo.code));
        nodes.push(row);
    }
    const cta = element("a", "Đặt vé áp dụng ngay", "button primary");
    cta.href = "/#lich-chieu";
    nodes.push(cta);
    openModal({ tag: promo.tag, title: promo.title, bodyNodes: nodes, origin });
}

async function loadPromotionsView() {
    show("promotions-view");
    await ensureCatalogData();
    $("promotions-grid").replaceChildren(...(catalogData.promotions || []).map((promo) => {
        const card = element("article", null, "promo-card");
        const top = element("div");
        top.append(
            element("span", promo.tag, "promo-tag"),
            element("h2", promo.title),
            element("p", promo.summary),
        );
        const bottom = element("div", null, "concessions-left");
        if (promo.code) {
            const codeBox = element("div", null, "promo-code-row");
            codeBox.append(element("code", promo.code));
            const copyBtn = element("button", "Sao chép", "button secondary");
            copyBtn.type = "button";
            copyBtn.style.minHeight = "34px";
            copyBtn.addEventListener("click", async () => {
                try {
                    await navigator.clipboard.writeText(promo.code);
                    copyBtn.textContent = "Đã chép";
                } catch {
                    copyBtn.textContent = promo.code;
                }
            });
            codeBox.append(copyBtn);
            bottom.append(codeBox);
        }
        const actions = element("div", null, "promo-actions");
        const detailBtn = element("button", "Xem thể lệ", "button secondary");
        detailBtn.type = "button";
        detailBtn.addEventListener("click", () => openPromoModal(promo, detailBtn));
        actions.append(detailBtn);
        bottom.append(actions);
        card.append(top, bottom);
        return card;
    }));
}

function openBlogModal(post, origin) {
    const nodes = [
        element("p", `${post.author} · ${post.published_label} · ${post.views.toLocaleString("vi-VN")} lượt xem`, "muted"),
        element("p", post.summary),
        element("p", post.content),
    ];
    if (post.movie_id) {
        const link = element("a", "Xem lịch chiếu & Đặt vé phim này", "button primary");
        link.href = `/?view=movie&id=${encodeURIComponent(post.movie_id)}`;
        nodes.push(link);
    }
    openModal({
        tag: post.category === "review" ? "Bình luận phim" : "Blog điện ảnh",
        title: post.title,
        bodyNodes: nodes,
        origin,
    });
}

function renderBlogCards() {
    const posts = (catalogData.blog_posts || []).filter(
        (p) => activeBlogCat === "all" || p.category === activeBlogCat,
    );
    $("blog-grid").replaceChildren(...posts.map((post) => {
        const card = element("article", null, "blog-card");
        const top = element("div");
        top.append(
            element("span", post.category === "review" ? "Bình luận phim" : "Blog điện ảnh", "promo-tag"),
            element("h2", post.title),
            element("p", post.summary),
        );
        const foot = element("div", null, "blog-meta");
        foot.append(element("span", `${post.author} · ${post.published_label}`), element("span", `${post.views.toLocaleString("vi-VN")} lượt xem`));
        const readBtn = element("button", "Đọc bài viết", "button secondary");
        readBtn.type = "button";
        readBtn.addEventListener("click", () => openBlogModal(post, readBtn));
        card.append(top, foot, readBtn);
        return card;
    }));
}

async function loadBlogView() {
    show("blog-view");
    await ensureCatalogData();
    document.querySelectorAll(".blog-tabs .movie-tab").forEach((tab) => {
        tab.onclick = () => {
            activeBlogCat = tab.dataset.blogCat;
            document.querySelectorAll(".blog-tabs .movie-tab").forEach((b) => {
                b.setAttribute("aria-selected", String(b === tab));
            });
            renderBlogCards();
        };
    });
    renderBlogCards();
}

/* ---------------- BOOKING STEP 1: SEATING ---------------- */
function stopSeatUpdates() {
    clearInterval(seatRefresh);
    seatEvents?.close();
    screening = null;
}

function renderBookingPoster(id, filmKey) {
    const container = $(id);
    const poster = filmArt.get(filmKey)?.poster ?? "";
    if (container.dataset.poster === poster) return;
    container.dataset.poster = poster;
    container.replaceChildren();
    container.hidden = !poster;
    if (!poster) return;
    const image = element("img");
    image.alt = "";
    image.src = `/assets/films/${poster}`;
    image.addEventListener("error", () => {
        if (image.parentNode === container) container.hidden = true;
    }, { once: true });
    container.append(image);
}

function openScreening(slot, origin) {
    stopSeatUpdates();
    screening = slot;
    seatList = [];
    seatOrigin = origin;
    selected = new Set();
    concessionQty = new Map();
    appliedPromoCode = "";
    redeemedPoints = 0;
    seatSignature = null;
    $("customer").value = currentAccount?.full_name || "";
    $("reload-seats").hidden = true;
    $("seats").replaceChildren(element("p", "Đang tải sơ đồ ghế…", "seat-message"));
    setText("seat-availability", "");
    setText("seating-format-badge", slot.format || "2D Phụ đề");
    setText("movie-title", slot.title);
    setText("movie-cinema", slot.cinema_name || "DUT Nguyễn Du");
    setText("movie-details", screeningLabel(slot));
    renderBookingPoster("seating-poster", slot.movie_id ?? slot.title);
    show("seating");
    window.scrollTo(0, 0);
    $("seating-heading").focus({ preventScroll: true });
    renderSelection();
    notice();
    void refreshSeats();
    seatEvents = new EventSource(`/api/screenings/${encodeURIComponent(slot.id)}/updates`);
    seatEvents.onmessage = refreshSeats;
    seatRefresh = setInterval(refreshSeats, 5000);
}

async function refreshSeats() {
    const id = screening?.id;
    if (!id || checkoutBusy) return;
    const request = ++seatRequest;
    try {
        const seats = await api(`/api/screenings/${encodeURIComponent(id)}/seats`);
        if (screening?.id !== id || request !== seatRequest || checkoutBusy) return;
        $("reload-seats").hidden = true;
        const signature = JSON.stringify(seats);
        if (signature === seatSignature) return;
        seatSignature = signature;
        seatList = seats;
        renderSeats(seats);
    } catch (error) {
        if (screening?.id !== id || request !== seatRequest || checkoutBusy) return;
        if (!seatSignature) {
            $("seats").replaceChildren(element("p", error.message, "seat-message"));
            $("reload-seats").hidden = false;
        }
    }
}

function orderedSelection() {
    return [...selected].sort(seatOrder.compare);
}

function currentSeatsTotal() {
    if (!screening) return 0;
    const byLabel = new Map(seatList.map((s) => [s.label, s]));
    let total = 0;
    for (const label of selected) {
        const seat = byLabel.get(label);
        total += seatUnitPrice(screening.base_price || 90000, seat?.seat_type || "STANDARD", screening.starts_at);
    }
    return total;
}

function hasSingleGapWarning() {
    const byRow = new Map();
    for (const seat of seatList) {
        if (seat.seat_type === "COUPLE") continue;
        const match = seat.label.match(/^([A-Z]+)(\d+)$/);
        if (!match) continue;
        const [, row, numStr] = match;
        if (!byRow.has(row)) byRow.set(row, []);
        byRow.get(row).push({
            num: Number(numStr),
            taken: seat.status !== "AVAILABLE" || selected.has(seat.label),
            selected: selected.has(seat.label),
        });
    }
    for (const items of byRow.values()) {
        items.sort((a, b) => a.num - b.num);
        if (!items.some((item) => item.selected)) continue;
        for (let i = 0; i < items.length; i += 1) {
            if (items[i].taken) continue;
            const leftTaken = i === 0 || items[i - 1].taken;
            const rightTaken = i === items.length - 1 || items[i + 1].taken;
            const nearSelected = (i > 0 && items[i - 1].selected) || (i < items.length - 1 && items[i + 1].selected);
            if (leftTaken && rightTaken && nearSelected) return true;
        }
    }
    return false;
}

function renderSelection() {
    $("selection").replaceChildren(...(selected.size
        ? orderedSelection().map((label) => element("span", label, "seat-chip"))
        : ["Chưa chọn ghế"]));
    setText("seat-subtotal", formatPrice.format(currentSeatsTotal()));
    $("to-concessions").disabled = checkoutBusy || !selected.size;
    $("customer").disabled = checkoutBusy;
}

function renderSeats(seats) {
    const focus = document.activeElement?.dataset.seat;
    const occupiedSelection = [];
    const rows = new Map();
    let available = 0;
    for (const seat of [...seats].sort((first, second) => seatOrder.compare(first.label, second.label))) {
        const row = seat.label.match(/^[A-Z]+/)[0];
        if (!rows.has(row)) {
            const group = element("div", null, "seat-row");
            const letter = element("span", row, "row-letter");
            letter.setAttribute("aria-hidden", "true");
            group.append(letter);
            rows.set(row, group);
        }
        const button = element("button", seat.label, "seat");
        button.type = "button";
        button.dataset.seat = seat.label;
        button.disabled = seat.status !== "AVAILABLE";
        if (!button.disabled) available += 1;
        if (button.disabled && selected.delete(seat.label)) occupiedSelection.push(seat.label);
        const status = seat.status === "SOLD" ? "Đã bán" : seat.status === "HELD" ? "Đang giữ" : "Trống";
        const premium = seat.seat_type === "PREMIUM";
        const couple = seat.seat_type === "COUPLE";
        const typeLabel = couple ? ", ghế đôi Sweetbox" : premium ? ", VIP" : "";
        button.setAttribute("aria-label", `${seat.label}, ${status}${typeLabel}`);
        button.classList.toggle("premium", premium);
        button.classList.toggle("couple", couple);
        button.classList.toggle("unavailable", button.disabled);
        button.classList.toggle("held", seat.status === "HELD");
        function update() {
            const pressed = selected.has(seat.label);
            button.classList.toggle("selected", pressed);
            button.setAttribute("aria-pressed", String(pressed));
        }
        update();
        button.addEventListener("click", () => {
            if (checkoutBusy) return;
            if (selected.has(seat.label)) selected.delete(seat.label);
            else if (selected.size < 8) selected.add(seat.label);
            else return notice("Mỗi đơn giữ tối đa 8 ghế.");
            update();
            renderSelection();
            notice(hasSingleGapWarning() ? "Lưu ý: Lựa chọn hiện tại đang để trống 1 ghế lẻ bên cạnh." : "");
        });
        rows.get(row).append(button);
    }
    const content = rows.size ? [...rows.values()] : [element("p", "Suất này chưa có sơ đồ ghế.", "seat-message")];
    $("seats").replaceChildren(...content);
    setText("seat-availability", seats.length ? `${available} ghế trống` : "");
    if (occupiedSelection.length) {
        notice(`Ghế ${occupiedSelection.join(", ")} vừa được giữ hoặc bán. Vui lòng chọn ghế khác.`);
    }
    if (focus) {
        const button = $("seats").querySelector(`[data-seat="${focus}"]:not(:disabled)`);
        (button || $("seats").querySelector(".seat:not(:disabled)") || $("seating-heading")).focus();
    }
    renderSelection();
}

$("reload-seats").addEventListener("click", refreshSeats);
$("back").addEventListener("click", () => {
    if (page.has("screening")) { location.assign("/#lich-chieu"); return; }
    stopSeatUpdates();
    notice();
    show("catalog");
    seatOrigin?.focus();
});

/* ---------------- BOOKING STEP 2: CONCESSIONS & PROMOTIONS ---------------- */
let quoteVersion = 0;
let quoteTimer = null;
let validQuote = false;

function bookingOptions() {
    return {
        concessions: [...concessionQty].filter(([, quantity]) => quantity > 0)
            .map(([id, quantity]) => ({ id, quantity })),
        promo_code: appliedPromoCode || null,
        redeem_points: redeemedPoints,
    };
}

function renderConcessionsSummary() {
    const options = bookingOptions();
    sessionStorage.setItem(`options-${bookingId}`, JSON.stringify(options));
    const version = ++quoteVersion;
    validQuote = false;
    $("hold").disabled = true;
    setText("summary-grand-total", "Đang tính…");
    setText("concessions-seats-list", booking.seats.join(", "));
    setText("summary-seats-price", formatPrice.format(booking.amount));
    clearTimeout(quoteTimer);
    quoteTimer = setTimeout(async () => {
        try {
            const quote = await post(`/api/bookings/${bookingId}/quote`, options);
            if (version !== quoteVersion || $("concessions-step").hidden) return;
            validQuote = true;
            setText("summary-concessions-price", formatPrice.format(quote.concessions_amount));
            $("summary-discount-row").hidden = !quote.discount_amount;
            setText("summary-discount-price", `−${formatPrice.format(quote.discount_amount)}`);
            setText("summary-grand-total", formatPrice.format(quote.amount));
            report("promo-feedback", [
                quote.promo_code && `Đã áp dụng ${quote.promo_code}.`,
                redeemedPoints && `Số điểm sẽ dùng: ${quote.points_redeemed}.`,
            ].filter(Boolean).join(" "));
            updateTimer();
        } catch (error) {
            if (version !== quoteVersion) return;
            setText("summary-grand-total", "Chưa chốt giá");
            report("promo-feedback", error.message);
            $("retry-quote").hidden = false;
        }
    }, 150);
    $("retry-quote").hidden = true;
}

$("retry-quote").addEventListener("click", renderConcessionsSummary);

function renderConcessionsStep() {
    setText("concessions-movie-title", booking.movie_title);
    setText("concessions-movie-details", `${booking.cinema_name || "DUT Nguyễn Du"} · ${screeningLabel(booking)}`);
    renderBookingPoster("concessions-poster", booking.movie_title);

    $("concession-list").replaceChildren(...(catalogData.concessions || []).map((item) => {
        const row = element("article", null, "concession-item");
        const info = element("div", null, "concession-info");
        const titleRow = element("div", null, "concession-title-row");
        titleRow.append(element("h3", item.name));
        if (item.badge) titleRow.append(element("span", item.badge, "promo-tag"));
        info.append(titleRow, element("p", item.description), element("span", formatPrice.format(item.price), "concession-price"));

        const ctrl = element("div", null, "qty-control");
        const dec = element("button", "−", "qty-btn");
        dec.type = "button";
        dec.setAttribute("aria-label", `Giảm ${item.name}`);
        const qtySpan = element("span", String(concessionQty.get(item.id) || 0), "qty-value");
        const inc = element("button", "+", "qty-btn");
        inc.type = "button";
        inc.setAttribute("aria-label", `Tăng ${item.name}`);
        function updateQuantity(quantity) {
            qtySpan.textContent = String(quantity);
            row.classList.toggle("in-cart", quantity > 0);
            dec.disabled = quantity === 0;
            inc.disabled = quantity >= 20;
        }
        function changeQuantity(delta) {
            const next = Math.max(0, Math.min(20, (concessionQty.get(item.id) || 0) + delta));
            concessionQty.set(item.id, next);
            updateQuantity(next);
            renderConcessionsSummary();
        }
        updateQuantity(concessionQty.get(item.id) || 0);
        dec.onclick = () => changeQuantity(-1);
        inc.onclick = () => changeQuantity(1);
        ctrl.append(dec, qtySpan, inc);
        row.append(info, ctrl);
        return row;
    }));

    const codePromos = (catalogData.promotions || []).filter((p) => p.code);
    $("promo-chips").replaceChildren(...codePromos.map((p) => {
        const chip = element("button", p.code, "promo-chip");
        chip.type = "button";
        chip.title = p.title;
        chip.onclick = () => {
            $("promo-code-input").value = p.code;
            appliedPromoCode = p.code;
            renderConcessionsSummary();
        };
        return chip;
    }));
    $("promo-code-input").value = appliedPromoCode;

    const canRedeem = Boolean(currentAccount && currentAccount.points > 0);
    $("redeem-points-box").hidden = !canRedeem;
    if (canRedeem) {
        setText("redeem-available", String(currentAccount.points));
        $("redeem-points-input").max = String(currentAccount.points);
        $("redeem-points-input").value = String(redeemedPoints);
    }

    renderConcessionsSummary();
}

$("checkout").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selected.size || !screening || checkoutBusy) return;
    checkoutBusy = true;
    renderSelection();
    const payload = { screening_id: screening.id, seats: orderedSelection(), customer_name: $("customer").value.trim() || null };
    try {
        const held = await post("/api/holds", payload, requestKey("hold-seats", payload));
        sessionStorage.removeItem("hold-seats");
        location.assign(orderUrl(held.id));
    } catch (error) {
        checkoutBusy = false;
        if (error.status === 409) {
            sessionStorage.removeItem("hold-seats");
            await refreshSeats();
        }
        notice(error.message);
        renderSelection();
    }
});

$("back-to-seats").addEventListener("click", async () => {
    if (checkoutBusy) return;
    checkoutBusy = true;
    try {
        await api(`/api/bookings/${bookingId}/cancel`, {method: "POST"});
        sessionStorage.removeItem(`options-${bookingId}`);
        location.replace(`/?screening=${encodeURIComponent(booking.screening_id)}`);
    } catch (error) {
        notice(error.message);
    } finally {
        checkoutBusy = false;
    }
});

$("apply-promo-btn").addEventListener("click", () => {
    appliedPromoCode = $("promo-code-input").value.trim().toUpperCase();
    renderConcessionsSummary();
});

$("redeem-points-input").addEventListener("input", () => {
    const maxPts = Math.min(currentAccount?.points || 0, 5000);
    redeemedPoints = Math.max(0, Math.min(maxPts, Math.floor(Number($("redeem-points-input").value) || 0)));
    $("redeem-points-input").value = String(redeemedPoints);
    renderConcessionsSummary();
});

$("redeem-max-btn").addEventListener("click", () => {
    const maxPts = Math.min(currentAccount?.points || 0, 5000);
    redeemedPoints = maxPts;
    $("redeem-points-input").value = String(redeemedPoints);
    renderConcessionsSummary();
});

async function prepareOrder(skipCombo) {
    if (checkoutBusy) return;
    const options = bookingOptions();
    if (skipCombo) options.concessions = [];
    checkoutBusy = true;
    paymentRevision += 1;
    $("concessions-step").inert = true;
    notice();
    try {
        const result = await post(`/api/bookings/${bookingId}/prepare`, options);
        ++quoteVersion;
        sessionStorage.removeItem(`options-${bookingId}`);
        payment = result.payment;
        openOrder(result.booking);
    } catch (error) {
        notice(error.message);
        void refreshOrder();
    } finally {
        checkoutBusy = false;
        $("concessions-step").inert = false;
    }
}

$("hold").addEventListener("click", () => prepareOrder(false));
$("skip-combo").addEventListener("click", () => prepareOrder(true));

/* ---------------- BOOKING STEP 3 & 4: PAYMENT & TICKETS ---------------- */
function updateTimer() {
    if (!booking) return;
    const awaiting = ["PROCESSING", "SUCCEEDED"].includes(payment?.status);
    const deadline = awaiting ? booking.expires_at : (booking.pay_by || booking.expires_at);
    const remaining = Math.max(0, Math.ceil((Date.parse(deadline) - Date.now() - clockOffset) / 1000));
    const minutes = Math.floor(remaining / 60);
    const seconds = String(remaining % 60).padStart(2, "0");
    if (!$("concessions-step").hidden) {
        setText("hold-timer", remaining ? `Đang giữ ${booking.seats.join(", ")} · Còn ${minutes}:${seconds}` : "Thời hạn giữ ghế đã kết thúc.");
        $("hold").disabled = checkoutBusy || !validQuote || !remaining;
        $("skip-combo").disabled = checkoutBusy || !remaining;
    }
    $("timer").hidden = booking.status !== "HELD";
    setText("timer", remaining ? `Giữ ghế còn ${minutes}:${seconds}` : "Đang cập nhật thời hạn giữ ghế…");
    const canStart = !booking.pay_by || Date.parse(booking.pay_by) > Date.now() + clockOffset;
    $("pay").disabled = paymentBusy || !remaining || !canStart;
    if (awaiting && remaining > 0) setText("timer", `Chờ xác nhận giao dịch · ${minutes}:${seconds}`);
    $("outcome").disabled = paymentBusy;
    $("delay").disabled = paymentBusy;
    $("simulate").setAttribute("aria-busy", String(paymentBusy));
    setText("pay", paymentBusy ? "Đang gửi thanh toán…" : payment?.status === "DECLINED" ? "Thử thanh toán lại" : "Thanh toán ngay");
}

function setBooking(value) {
    booking = value;
    clockOffset = Date.parse(value.server_now) - Date.now();
}

function openOrder(value) {
    missingOrder = false;
    bookingId = value.id;
    history.replaceState(null, "", orderUrl(bookingId));
    setBooking(value);
    show("order");
    renderOrder();
    window.scrollTo(0, 0);
    $("order-heading").focus({ preventScroll: true });
    void refreshOrder();
}

function ticketCard(ticket, details, showLink = true) {
    const card = element("article", null, "ticket");
    const info = element("div", null, "ticket-info");
    info.append(
        element("p", `Ghế ${ticket.seat}`, "ticket-seat"),
        element(showLink ? "h2" : "h3", details.movie_title),
        element("p", `${details.cinema_name || "DUT Nguyễn Du"} · ${details.screening_format || "2D"}`),
        element("p", screeningLabel(details)),
    );
    if (ticket.customer_name) info.append(element("p", ticket.customer_name, "ticket-holder"));
    if (ticket.checked_in_at) {
        info.append(element("p", `Đã soát vé: ${shortTime(ticket.checked_in_at)} · ${formatShortDate.format(new Date(ticket.checked_in_at))}`, "cinema-line"));
    }
    const code = element("div", null, "ticket-code");
    const path = `/api/tickets/${encodeURIComponent(ticket.code)}`;
    const qr = element("img");
    qr.alt = `Mã QR vé ghế ${ticket.seat}`;
    qr.width = 128;
    qr.height = 128;
    qr.src = `${path}/qr.svg`;
    code.append(qr);
    if (showLink) {
        const link = element("a", "Chi tiết vé");
        link.href = `/?view=tickets&ticket=${encodeURIComponent(ticket.code)}`;
        link.setAttribute("aria-label", `Chi tiết vé ghế ${ticket.seat}`);
        code.append(link);
    }
    card.append(info, code);
    return card;
}

function renderOrderAccess() {
    const saved = booking.saved;
    $("order-access").hidden = false;
    $("save-order").hidden = saved;
    $("order-saved").hidden = !saved;
    $("print-tickets").hidden = booking.status !== "CONFIRMED";
    setText("order-code", booking.id);
}

function renderOrder() {
    const confirmed = booking.status === "CONFIRMED";
    const expired = booking.status === "EXPIRED";
    const cancelled = booking.status === "CANCELLED";
    const tickets = booking.tickets || [];
    const refunded = payment?.status === "REFUNDED";
    const state = (expired || cancelled) && !refunded ? booking.status : payment?.status;

    $("order-tools").hidden = confirmed;
    $("order-summary").hidden = false;
    $("retry-booking").hidden = !expired && !cancelled;
    $("ticket-return").hidden = !confirmed;
    $("order-intro").hidden = !confirmed;
    showStage(confirmed ? "step-tickets" : "step-payment");
    setText("order-heading", confirmed ? "Vé của bạn" : "Thanh toán");
    if (confirmed) setText("order-intro", `${tickets.length} vé điện tử · Đặt vé thành công`);

    setText("order-format-badge", booking.screening_format || "2D Phụ đề");
    setText("order-title", booking.movie_title);
    setText("order-cinema", booking.cinema_name || "DUT Nguyễn Du");
    setText("order-details", screeningLabel(booking));
    renderBookingPoster("order-poster", booking.movie_title);
    setText("order-seats", booking.seats.join(", "));

    const concessions = booking.concessions || [];
    $("order-concessions-row").hidden = concessions.length === 0;
    if (concessions.length) {
        setText("order-concessions", concessions.map((c) => `${c.name} ×${c.quantity} · ${formatPrice.format(c.total)}`).join(", "));
    }
    $("order-discount-row").hidden = !(booking.discount_amount > 0);
    if (booking.discount_amount > 0) {
        setText("order-discount", `-${formatPrice.format(booking.discount_amount)}`);
    }
    setText("order-seat-price", formatPrice.format(booking.amount + booking.discount_amount - booking.concessions_amount));
    setText("order-points", String(booking.points_redeemed || 0));
    $("order-points-row").hidden = !booking.points_redeemed;
    setText("amount", formatPrice.format(booking.amount));

    const status = $("payment-status");
    status.dataset.state = state || "";
    status.hidden = false;
    const statusText = state === "EXPIRED"
        ? "Đơn đã hết hạn giữ ghế."
        : state === "CANCELLED"
            ? "Bạn đã hủy giữ ghế. Các ghế đã được mở lại."
            : paymentLabels[state] || "Đang tải trạng thái thanh toán…";
    setText("payment-status", statusText);

    const canSimulate = booking.status === "HELD" && ["PENDING", "DECLINED"].includes(payment?.status);
    $("simulate").hidden = !canSimulate;
    $("cancel-hold").hidden = !canSimulate;
    updateTimer();
    renderOrderAccess();

    const signature = tickets.map((ticket) => ticket.code).join(",");
    if (signature !== shownTickets) {
        shownTickets = signature;
        $("tickets").replaceChildren(...tickets.map((ticket) => ticketCard(ticket, booking)));
    }

    $("concession-voucher").hidden = !(confirmed && concessions.length);
    if (confirmed && concessions.length) {
        setText("voucher-cinema", `Quầy Bắp Nước · ${booking.cinema_name || "DUT Nguyễn Du"}`);
        setText("voucher-items", concessions.map((c) => `${c.name} × ${c.quantity}`).join(" · "));
        setText("voucher-code", `F&B-${booking.id.slice(0, 8).toUpperCase()}`);
    }
}

async function refreshOrder() {
    if (!bookingId || missingOrder || loadingOrder || paymentBusy || checkoutBusy || booking?.tickets?.length) return;
    loadingOrder = true;
    const revision = paymentRevision;
    const path = `/api/bookings/${encodeURIComponent(bookingId)}`;
    try {
        const value = await api(path);
        if (checkoutBusy || revision !== paymentRevision) return;
        setBooking(value);
        if (booking.checkout_phase === "DRAFT" && booking.status === "HELD") {
            if ($("concessions-step").hidden) {
                await Promise.all([ensureCatalogData(), loadAccount()]);
                const options = JSON.parse(sessionStorage.getItem(`options-${bookingId}`) || "{}");
                concessionQty = new Map((options.concessions || []).map(item => [item.id, item.quantity]));
                appliedPromoCode = options.promo_code || "";
                redeemedPoints = options.redeem_points || 0;
                show("concessions-step");
                renderConcessionsStep();
                $("concessions-heading").focus({preventScroll:true});
            }
            updateTimer();
            return;
        }
        if (!$("concessions-step").hidden) show("order");
        renderOrder();
        if (booking.checkout_phase !== "DRAFT" && booking.status !== "CONFIRMED" && payment?.status !== "REFUNDED") {
            let nextPayment;
            try {
                nextPayment = await api(`${path}/payment`);
            } catch (error) {
                if (error.status !== 404 || booking.checkout_phase !== "READY" || booking.status !== "HELD") throw error;
                nextPayment = await post(`${path}/payment`, {});
            }
            if (revision === paymentRevision) {
                payment = nextPayment;
                renderOrder();
            }
        }
        if (!$("reload-order").hidden) notice();
        $("reload-order").hidden = true;
    } catch (error) {
        missingOrder = !booking && [404, 422].includes(error.status);
        if (missingOrder) setText("order-intro", "Không mở được đơn. Hãy kiểm tra mã hoặc đăng nhập bằng tài khoản đã đặt.");
        $("reload-order").hidden = missingOrder;
        notice(missingOrder ? "" : error.message);
    } finally {
        loadingOrder = false;
    }
}

$("simulate").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (paymentBusy || $("pay").disabled) return;
    const payload = { outcome: $("outcome").value, delay_seconds: Number($("delay").value) };
    const slot = `payment-${bookingId}`;
    paymentBusy = true;
    paymentRevision += 1;
    updateTimer();
    notice();
    try {
        payment = await post(`/api/bookings/${encodeURIComponent(bookingId)}/payment/simulate`, payload, requestKey(slot, payload));
        sessionStorage.removeItem(slot);
        renderOrder();
    } catch (error) {
        if (error.status === 409) sessionStorage.removeItem(slot);
        notice(error.message);
    } finally {
        paymentBusy = false;
        updateTimer();
        void refreshOrder();
    }
});

$("cancel-hold").addEventListener("click", async () => {
    const btn = $("cancel-hold");
    btn.disabled = true;
    try {
        const cancelled = await api(`/api/bookings/${encodeURIComponent(bookingId)}/cancel`, { method: "POST" });
        sessionStorage.removeItem(`options-${bookingId}`);
        location.replace(`/?screening=${encodeURIComponent(cancelled.screening_id)}`);
    } catch (error) {
        notice(error.message);
    } finally {
        btn.disabled = false;
    }
});

$("print-tickets").addEventListener("click", () => window.print());
$("reload-order").addEventListener("click", refreshOrder);

$("save-order").addEventListener("click", async () => {
    const button = $("save-order");
    button.disabled = true;
    try {
        await api(`/api/my-bookings/${encodeURIComponent(booking.id)}`, { method: "PUT" });
        booking.saved = true;
        renderOrderAccess();
        $("copy-order").focus();
        report("order-access-status");
    } catch (error) {
        report("order-access-status", error.message);
    } finally {
        button.disabled = false;
    }
});

$("copy-order").addEventListener("click", async () => {
    try {
        await navigator.clipboard.writeText(booking.id);
        report("order-access-status", "Đã sao chép mã đơn.");
    } catch {
        report("order-access-status", "Hãy chọn và sao chép mã đơn ở trên.");
    }
});

/* ---------------- MY TICKETS ---------------- */
function savedOrderRow(order) {
    const row = element("li", null, "history-row");
    const info = element("div", null, "history-info");
    const state = element("span", bookingLabels[order.status] || "Kiểm tra trạng thái", "history-state");
    state.dataset.state = order.status;
    info.append(
        state,
        element("h3", order.movie_title),
        element("p", `${order.cinema_name || "DUT Nguyễn Du"} · ${screeningLabel(order)}`, "muted"),
        element("p", `Ghế ${order.seats.join(", ")}${order.amount ? ` · ${formatPrice.format(order.amount)}` : ""}`, "history-seats"),
    );
    const actions = element("div", null, "history-actions");
    const link = element("a", order.status === "CONFIRMED" ? "Xem vé" : "Mở đơn", "button secondary history-open");
    link.href = orderUrl(order.id);
    const remove = element("button", "Bỏ lưu", "history-remove");
    remove.type = "button";
    remove.setAttribute("aria-label", `Bỏ lưu đơn ${order.movie_title}, ghế ${order.seats.join(", ")}`);
    remove.addEventListener("click", async () => {
        remove.disabled = true;
        try {
            await api(`/api/my-bookings/${encodeURIComponent(order.id)}`, { method: "DELETE" });
            row.remove();
            $("saved-orders-empty").hidden = $("saved-orders-list").childElementCount > 0;
            ($("saved-orders-list").querySelector(".history-open") || $("lookup-code")).focus();
            report("history-status", "Đã bỏ lưu đơn.");
        } catch (error) {
            report("history-status", error.message);
        } finally {
            remove.disabled = false;
        }
    });
    actions.append(link, remove);
    row.append(info, actions);
    return row;
}

async function loadSavedOrders() {
    $("reload-history").hidden = true;
    report("history-status", "Đang tải đơn đã lưu…");
    try {
        const { scope, bookings: orders } = await api("/api/my-bookings");
        const signedIn = scope === "account";
        setText("saved-orders-scope", signedIn
            ? "Các đơn được đồng bộ theo tài khoản thành viên của bạn."
            : "Các đơn đặt với vai trò khách gắn với trình duyệt này.");
        $("saved-orders-scope").hidden = false;
        $("history-sign-in").hidden = signedIn;
        $("saved-orders-list").replaceChildren(...orders.map(savedOrderRow));
        $("saved-orders-empty").hidden = orders.length > 0;
        report("history-status");
    } catch (error) {
        $("reload-history").hidden = false;
        report("history-status", error.message);
    }
}

$("reload-history").addEventListener("click", loadSavedOrders);

async function lookupCode(rawCode, ticketOnly = false) {
    const code = rawCode.trim().toLowerCase();
    const input = $("lookup-code");
    input.value = rawCode.trim();
    if (!/^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/.test(code)) {
        report("lookup-status", "Mã chưa đúng định dạng. Hãy sao chép đủ mã đơn hoặc mã vé.", "ERROR");
        input.setAttribute("aria-invalid", "true");
        return;
    }

    $("lookup-submit").disabled = true;
    report("lookup-status", "Đang tra cứu…");
    try {
        if (!ticketOnly) {
            const order = await api(`/api/bookings/${code}`).catch((error) => {
                if (error.status === 404) return null;
                throw error;
            });
            if (order) {
                openOrder(order);
                return;
            }
        }
        const ticket = await api(`/api/tickets/${code}`);
        $("lookup-ticket").replaceChildren(ticketCard(ticket, ticket, false));
        setText("lookup-ticket-code", ticket.code);
        $("lookup-result").hidden = false;
        report("lookup-status");
        $("lookup-result").focus();
    } catch (error) {
        const message = error.status === 404
            ? "Không tìm thấy đơn hoặc vé với mã này. Với đơn theo tài khoản, hãy đăng nhập bằng tài khoản đã đặt."
            : error.message;
        report("lookup-status", message, "ERROR");
    } finally {
        $("lookup-submit").disabled = false;
    }
}

$("lookup-code").addEventListener("input", () => {
    $("lookup-code").removeAttribute("aria-invalid");
    report("lookup-status");
});

/* ---------------- ACCOUNT & D-STAR MEMBERSHIP ---------------- */
function configureSignIn() {
    if (!signingUp) return;
    setText("auth-form-title", "Tạo tài khoản thành viên");
    setText("auth-submit", "Đăng ký");
    setText("auth-mode-link", "Đã có tài khoản? Đăng nhập");
    $("auth-mode-link").href = "/?view=account";
    $("username-help").hidden = false;
    $("password-help").hidden = false;
    $("username").setAttribute("aria-describedby", "username-help");
    $("password").setAttribute("aria-describedby", "password-help");
    $("password").autocomplete = "new-password";
    $("password").minLength = 15;
}

function renderMemberProfile(profile) {
    setText("member-tier-badge", profile.tier?.name || "Member");
    setText("account-username", profile.full_name ? `${profile.full_name} (@${profile.username})` : `@${profile.username}`);
    setText("member-points", String(profile.points || 0));
    setText("member-spent", formatPrice.format(profile.total_spent || 0));
    if (profile.tier?.next_tier) {
        setText("member-next-tier", `Còn ${formatPrice.format(profile.tier.remaining)} lên ${profile.tier.next_tier}`);
    } else {
        setText("member-next-tier", "Hạng cao nhất X-Star");
    }
    $("member-progress-bar").style.width = `${profile.tier?.progress ?? 0}%`;

    $("profile-fullname").value = profile.full_name || "";
    $("profile-email").value = profile.email || "";
    $("profile-phone").value = profile.phone || "";
    $("profile-birthdate").value = profile.birth_date || "";

    const txs = profile.point_history || [];
    $("point-history-empty").hidden = txs.length > 0;
    $("point-history-list").replaceChildren(...txs.map((tx) => {
        const li = element("li", null, "point-tx-row");
        const left = element("div");
        left.append(element("p", tx.description), element("small", formatShortDate.format(new Date(tx.created_at)), "muted"));
        const delta = element("span", `${tx.points_delta > 0 ? "+" : ""}${tx.points_delta} Star`, `point-tx-delta ${tx.points_delta >= 0 ? "pos" : "neg"}`);
        li.append(left, delta);
        return li;
    }));
}

async function loadAccount() {
    const showingAccount = !$("account").hidden;
    if (showingAccount) {
        $("reload-account").hidden = true;
        report("account-status", "Đang tải thông tin tài khoản…");
    }
    try {
        const { account } = await api("/api/auth/session");
        currentAccount = account;
        $("account-link").hidden = Boolean(account);
        $("user-menu").hidden = !account;
        $("mobile-logout-btn").hidden = !account;
        if (account) {
            setText("user-menu-name", account.full_name || account.username);
            setText("user-menu-tier", account.tier?.name || "Member");
            const pts = account.points || 0;
            setText("user-menu-stars", `${pts} ${pts === 1 ? "Star" : "Stars"}`);
        }
        const isStaffOrAdmin = Boolean(account && ["ADMIN", "STAFF"].includes(account.role));
        const adminLabel = account?.role === "STAFF" ? "Soát vé" : "Quản trị";
        $("admin-nav-link").hidden = !isStaffOrAdmin;
        setText("admin-nav-link", adminLabel);
        $("dropdown-admin-link").hidden = !isStaffOrAdmin;
        setText("dropdown-admin-label", adminLabel);
        $("mobile-admin-link").hidden = !isStaffOrAdmin;
        $("account-admin-shortcut").hidden = !isStaffOrAdmin;
        setText("account-admin-shortcut", account?.role === "STAFF" ? "Mở quầy Soát vé QR" : "Mở trang Quản trị");
        if (currentView === "admin") {
            void loadAdminView();
        }
        if (showingAccount) {
            $("account-guest-grid").hidden = Boolean(account);
            $("account-profile").hidden = !account;
            if (account) {
                const fullProfile = await api("/api/account/profile");
                renderMemberProfile(fullProfile);
            }
            report("account-status");
        }
    } catch (error) {
        if (showingAccount) {
            $("reload-account").hidden = false;
            report("account-status", error.message);
        }
    }
}

function accountChanged() {
    try {
        sessionStorage.removeItem("checkout");
    } catch {
        // Ignore storage access errors.
    }
}

accountUpdates?.addEventListener("message", () => {
    accountChanged();
    location.reload();
});

$("sign-in").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("auth-submit");
    button.disabled = true;
    report("auth-status", signingUp ? "Đang tạo tài khoản…" : "Đang đăng nhập…");
    try {
        await api(`/api/auth/${signingUp ? "register" : "login"}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: $("username").value, password: $("password").value }),
        });
        accountChanged();
        accountUpdates?.postMessage("changed");
        location.replace("/?view=account");
    } catch (error) {
        const message = error.status === 422 ? "Hãy kiểm tra định dạng tên đăng nhập và độ dài mật khẩu." : error.message;
        report("auth-status", message, "ERROR");
        button.disabled = false;
    }
});

$("profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const btn = $("profile-save");
    btn.disabled = true;
    report("profile-status", "Đang lưu thông tin…");
    try {
        await api("/api/account/profile", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                full_name: $("profile-fullname").value,
                email: $("profile-email").value,
                phone: $("profile-phone").value,
                birth_date: $("profile-birthdate").value || null,
            }),
        });
        await loadAccount();
        report("profile-status", "Đã cập nhật thông tin thành viên.");
    } catch (error) {
        report("profile-status", error.message, "ERROR");
    } finally {
        btn.disabled = false;
    }
});

$("password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const btn = $("password-save");
    btn.disabled = true;
    report("password-status", "Đang cập nhật mật khẩu…");
    try {
        await api("/api/account/password", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                current_password: $("current-password").value,
                new_password: $("new-password").value,
            }),
        });
        $("current-password").value = "";
        $("new-password").value = "";
        report("password-status", "Đã đổi mật khẩu thành công.");
    } catch (error) {
        report("password-status", error.message, "ERROR");
    } finally {
        btn.disabled = false;
    }
});

async function performLogout(button, statusId = "logout-status") {
    if (button) button.disabled = true;
    report(statusId, "Đang đăng xuất…");
    try {
        await api("/api/auth/logout", { method: "POST" });
        accountChanged();
        accountUpdates?.postMessage("changed");
        location.replace("/?view=account");
    } catch (error) {
        report(statusId, error.message, "ERROR");
        if (button) button.disabled = false;
    }
}

$("sign-out").addEventListener("click", () => void performLogout($("sign-out"), "logout-status"));
$("header-logout-btn").addEventListener("click", () => void performLogout($("header-logout-btn")));
$("mobile-logout-btn").addEventListener("click", () => void performLogout($("mobile-logout-btn")));

$("reload-account").addEventListener("click", loadAccount);

/* ---------------- ADMIN & STAFF PORTAL ---------------- */
let activeAdminTab = "overview";
let adminCatalog = {
    movies: [], cinemas: [], auditoriums: [], screenings: [],
    concessions: [], promotions: [], blog_posts: [],
};

function switchAdminTab(tabName) {
    activeAdminTab = tabName;
    document.querySelectorAll("#admin-tablist .movie-tab").forEach((btn) => {
        btn.setAttribute("aria-selected", String(btn.dataset.adminTab === tabName));
    });
    for (const id of ["overview", "checkin", "movies", "screenings", "concessions", "blog"]) {
        $(`admin-tab-${id}`).hidden = id !== tabName;
    }
}

document.querySelectorAll("#admin-tablist .movie-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchAdminTab(btn.dataset.adminTab));
});

function renderAdminOverview(overview) {
    const kpi = overview.kpi || {};
    setText("kpi-revenue", formatPrice.format(kpi.total_revenue || 0));
    setText(
        "kpi-revenue-sub",
        `Bắp nước: ${formatPrice.format(kpi.concessions_revenue || 0)} · Giảm giá: ${formatPrice.format(kpi.discount_total || 0)}`,
    );
    setText("kpi-bookings", `${kpi.confirmed_bookings || 0} đơn xác nhận`);
    setText(
        "kpi-bookings-sub",
        `Đang giữ: ${kpi.held_bookings || 0} · Hủy/Hết hạn: ${(kpi.cancelled_bookings || 0) + (kpi.expired_bookings || 0)}`,
    );
    setText("kpi-tickets", `${kpi.tickets_checked_in || 0} / ${kpi.tickets_sold || 0}`);
    setText("kpi-members", `${kpi.total_members || 0} tài khoản`);

    $("admin-rev-movie-body").replaceChildren(...((overview.by_movie || []).length
        ? overview.by_movie.map((row) => {
            const tr = element("tr");
            tr.append(
                element("td", row.movie_title),
                element("td", String(row.bookings_count)),
                element("td", String(row.seats_sold)),
                element("td", formatPrice.format(row.revenue)),
            );
            return tr;
        })
        : [ (() => { const tr = element("tr"); const td = element("td", "Chưa có đơn xác nhận.", "muted"); td.colSpan = 4; tr.append(td); return tr; })() ]));

    $("admin-rev-cinema-body").replaceChildren(...((overview.by_cinema || []).length
        ? overview.by_cinema.map((row) => {
            const tr = element("tr");
            tr.append(
                element("td", row.cinema_name),
                element("td", String(row.bookings_count)),
                element("td", String(row.seats_sold)),
                element("td", formatPrice.format(row.revenue)),
            );
            return tr;
        })
        : [ (() => { const tr = element("tr"); const td = element("td", "Chưa có đơn xác nhận.", "muted"); td.colSpan = 4; tr.append(td); return tr; })() ]));
}

async function loadAdminBookings() {
    const status = $("admin-booking-status").value;
    const q = $("admin-booking-q").value.trim();
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (q) params.set("q", q);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const rows = await api(`/api/admin/bookings${suffix}`);
    $("admin-bookings-body").replaceChildren(...(rows.length
        ? rows.map((row) => {
            const tr = element("tr");
            const codeCell = element("td");
            const codeLink = element("a", String(row.id).slice(0, 8));
            codeLink.href = orderUrl(row.id);
            codeLink.title = row.id;
            codeCell.append(codeLink);

            const filmCell = element("td");
            filmCell.append(element("strong", row.movie_title), element("p", `${row.cinema_name} · ${row.auditorium}`, "muted"));

            const stateSpan = element("span", bookingLabels[row.status] || row.status, "history-state");
            stateSpan.dataset.state = row.status;
            const stateCell = element("td");
            stateCell.append(stateSpan);

            const guestLabel = row.customer_name || (row.account_username ? `@${row.account_username}` : "Khách");
            tr.append(
                codeCell,
                filmCell,
                element("td", `${shortTime(row.starts_at)} · ${formatShortDate.format(new Date(row.starts_at))}`),
                element("td", (row.seats || []).join(", ")),
                element("td", guestLabel),
                element("td", formatPrice.format(row.amount || 0)),
                stateCell,
            );
            return tr;
        })
        : [ (() => { const tr = element("tr"); const td = element("td", "Không có đơn đặt vé phù hợp.", "muted"); td.colSpan = 7; tr.append(td); return tr; })() ]));
}

$("admin-booking-status").addEventListener("change", () => void loadAdminBookings());
$("admin-booking-q").addEventListener("input", () => void loadAdminBookings());

function renderInspectedTicket(ticket) {
    $("admin-ticket-card").hidden = false;
    const checked = Boolean(ticket.checked_in_at);
    const badge = $("admin-ticket-badge");
    badge.textContent = checked ? "ĐÃ CHECK-IN VÀO RẠP" : "HỢP LỆ · CHƯA SỬ DỤNG";
    badge.dataset.state = checked ? "EXPIRED" : "CONFIRMED";

    const rows = [
        ["Mã vé", ticket.code],
        ["Phim", ticket.movie_title],
        ["Cụm rạp & Phòng", `${ticket.cinema_name || "DUT Nguyễn Du"} · ${ticket.auditorium} (${ticket.screening_format || "2D"})`],
        ["Suất chiếu", `${shortTime(ticket.starts_at)} · ${dateLabel(ticket.starts_at)}`],
        ["Số ghế", ticket.seat],
        ["Tên khách", ticket.customer_name || "Không ghi tên"],
        ["Trạng thái soát vé", checked ? `Đã vào rạp lúc ${shortTime(ticket.checked_in_at)} (${formatShortDate.format(new Date(ticket.checked_in_at))})` : "Chưa soát vé"],
    ];
    $("admin-ticket-facts").replaceChildren(...rows.map(([k, v]) => {
        const div = element("div");
        div.append(element("dt", k), element("dd", v));
        return div;
    }));
}

$("admin-ticket-inspect-btn").addEventListener("click", async () => {
    const code = $("admin-ticket-code").value.trim().toLowerCase();
    if (!code) return;
    report("admin-checkin-feedback", "Đang kiểm tra vé…");
    try {
        const ticket = await api(`/api/tickets/${encodeURIComponent(code)}`);
        renderInspectedTicket(ticket);
        report("admin-checkin-feedback");
    } catch (error) {
        $("admin-ticket-card").hidden = true;
        report("admin-checkin-feedback", error.message, "ERROR");
    }
});

$("admin-checkin-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const code = $("admin-ticket-code").value.trim().toLowerCase();
    if (!code) return;
    const btn = $("admin-ticket-checkin-btn");
    btn.disabled = true;
    report("admin-checkin-feedback", "Đang xác nhận check-in…");
    try {
        const ticket = await api(`/api/admin/tickets/${encodeURIComponent(code)}/check-in`, { method: "POST" });
        renderInspectedTicket(ticket);
        report("admin-checkin-feedback", `Đã check-in thành công ghế ${ticket.seat} (${ticket.movie_title})!`);
    } catch (error) {
        report("admin-checkin-feedback", error.message, "ERROR");
        try {
            renderInspectedTicket(await api(`/api/tickets/${encodeURIComponent(code)}`));
        } catch {
            // Ignore secondary lookup error
        }
    } finally {
        btn.disabled = false;
    }
});

function populateMovieForm(movie) {
    $("am-id").value = movie.id;
    $("am-title").value = movie.title;
    $("am-genre").value = movie.genre;
    $("am-duration").value = String(movie.duration_minutes);
    $("am-status").value = movie.release_status || "NOW_SHOWING";
    $("am-age").value = movie.age_rating || "P";
    $("am-rating").value = String(movie.rating ?? 8.5);
    $("am-release").value = movie.release_date || "";
    $("am-director").value = movie.director || "";
    $("am-country").value = movie.country || "Việt Nam";
    $("am-cast").value = movie.cast_list || "";
    $("am-trailer").value = movie.trailer_url || "";
    $("am-poster").value = movie.poster_url || "";
    $("am-imax").checked = Boolean(movie.is_imax);
    $("am-synopsis").value = movie.synopsis || "";
    $("am-id").focus();
}

function resetMovieForm() {
    $("admin-movie-form").reset();
    $("am-duration").value = "115";
    $("am-rating").value = "8.8";
    $("am-country").value = "Việt Nam";
    report("am-feedback");
}

$("admin-movie-reset").addEventListener("click", resetMovieForm);

$("admin-movie-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    report("am-feedback", "Đang lưu phim…");
    try {
        const payload = {
            id: $("am-id").value.trim().toLowerCase(),
            title: $("am-title").value.trim(),
            genre: $("am-genre").value.trim(),
            duration_minutes: Number($("am-duration").value),
            release_status: $("am-status").value,
            age_rating: $("am-age").value,
            rating: Number($("am-rating").value),
            release_date: $("am-release").value || null,
            director: $("am-director").value.trim(),
            country: $("am-country").value.trim() || "Việt Nam",
            cast_list: $("am-cast").value.trim(),
            trailer_url: $("am-trailer").value.trim(),
            poster_url: $("am-poster").value.trim(),
            is_imax: $("am-imax").checked,
            synopsis: $("am-synopsis").value.trim(),
        };
        await post("/api/admin/movies", payload);
        catalogData = { screenings: [], coming_soon: [], cinemas: [], concessions: [], promotions: [], blog_posts: [] };
        await refreshAdminCatalog();
        report("am-feedback", `Đã lưu phim "${payload.title}".`);
    } catch (error) {
        report("am-feedback", error.message, "ERROR");
    }
});

function toLocalDatetimeValue(isoString) {
    const d = new Date(isoString);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function resetScreeningForm() {
    $("admin-screening-form").reset();
    const tomorrow = new Date(Date.now() + 24 * 3600 * 1000);
    tomorrow.setMinutes(0, 0, 0);
    $("as-starts").value = toLocalDatetimeValue(tomorrow.toISOString());
    $("as-price").value = "85000";
    report("as-feedback");
}

$("admin-screening-reset").addEventListener("click", resetScreeningForm);

$("admin-screening-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    report("as-feedback", "Đang lưu suất chiếu…");
    try {
        const customId = $("as-id").value.trim();
        const payload = {
            id: customId || null,
            movie_id: $("as-movie").value,
            auditorium_id: $("as-auditorium").value,
            starts_at: new Date($("as-starts").value).toISOString(),
            format: $("as-format").value,
            base_price: Number($("as-price").value),
            is_special: $("as-special").checked,
        };
        await post("/api/admin/screenings", payload);
        catalogData = { screenings: [], coming_soon: [], cinemas: [], concessions: [], promotions: [], blog_posts: [] };
        await refreshAdminCatalog();
        report("as-feedback", "Đã lưu suất chiếu thành công.");
    } catch (error) {
        report("as-feedback", error.message, "ERROR");
    }
});

$("admin-auditorium-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    report("aa-feedback", "Đang tạo phòng chiếu…");
    try {
        const payload = {
            id: $("aa-id").value.trim().toLowerCase(),
            name: $("aa-name").value.trim(),
            cinema_id: $("aa-cinema").value,
            screen_format: $("aa-format").value.trim(),
            standard_rows: Number($("aa-std").value),
            vip_rows: Number($("aa-vip").value),
            couple_seats: Number($("aa-couple").value),
            seats_per_row: Number($("aa-cols").value),
        };
        const created = await post("/api/admin/auditoriums", payload);
        await refreshAdminCatalog();
        report("aa-feedback", `Đã tạo ${created.name} với ${created.seat_count} ghế.`);
    } catch (error) {
        report("aa-feedback", error.message, "ERROR");
    }
});

$("admin-concession-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    report("ac-feedback", "Đang lưu combo…");
    try {
        const payload = {
            id: $("ac-id").value.trim().toLowerCase(),
            name: $("ac-name").value.trim(),
            price: Number($("ac-price").value),
            badge: $("ac-badge").value.trim() || null,
            description: $("ac-desc").value.trim(),
            category: "Combo",
            active: $("ac-active").checked,
            sort_order: 1,
        };
        await post("/api/admin/concessions", payload);
        catalogData = { screenings: [], coming_soon: [], cinemas: [], concessions: [], promotions: [], blog_posts: [] };
        await refreshAdminCatalog();
        report("ac-feedback", `Đã lưu "${payload.name}".`);
    } catch (error) {
        report("ac-feedback", error.message, "ERROR");
    }
});

$("admin-promo-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    report("ap-feedback", "Đang lưu khuyến mãi…");
    try {
        const payload = {
            id: $("ap-id").value.trim().toLowerCase(),
            tag: $("ap-tag").value.trim(),
            code: $("ap-code").value.trim().toUpperCase() || null,
            discount_type: $("ap-type").value,
            discount_value: Number($("ap-value").value),
            min_amount: Number($("ap-min").value),
            title: $("ap-title").value.trim(),
            summary: $("ap-summary").value.trim(),
            details: $("ap-details").value.trim() || $("ap-summary").value.trim(),
            valid_until: "31/12/2026",
            active: $("ap-active").checked,
            sort_order: 1,
        };
        await post("/api/admin/promotions", payload);
        catalogData = { screenings: [], coming_soon: [], cinemas: [], concessions: [], promotions: [], blog_posts: [] };
        await refreshAdminCatalog();
        report("ap-feedback", `Đã lưu khuyến mãi "${payload.title}".`);
    } catch (error) {
        report("ap-feedback", error.message, "ERROR");
    }
});

$("admin-blog-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    report("ab-feedback", "Đang lưu bài viết…");
    try {
        const payload = {
            id: $("ab-id").value.trim().toLowerCase(),
            category: $("ab-cat").value,
            author: $("ab-author").value.trim(),
            movie_id: $("ab-movie").value.trim() || null,
            title: $("ab-title").value.trim(),
            summary: $("ab-summary").value.trim(),
            content: $("ab-content").value.trim(),
            published_label: "Vừa xong",
            views: 120,
            sort_order: 1,
        };
        await post("/api/admin/blog-posts", payload);
        catalogData = { screenings: [], coming_soon: [], cinemas: [], concessions: [], promotions: [], blog_posts: [] };
        await refreshAdminCatalog();
        report("ab-feedback", `Đã đăng "${payload.title}".`);
    } catch (error) {
        report("ab-feedback", error.message, "ERROR");
    }
});

function renderAdminCatalogTables() {
    setText("admin-movie-total", String((adminCatalog.movies || []).length));
    $("admin-movies-body").replaceChildren(...(adminCatalog.movies || []).map((movie) => {
        const tr = element("tr");
        const titleCell = element("td");
        titleCell.append(element("strong", movie.title), element("p", `${movie.id} · ${movie.genre} · ${movie.duration_minutes}p`, "muted"));
        const statusBadge = element("span", movie.release_status === "COMING_SOON" ? "Sắp chiếu" : "Đang chiếu", "history-state");
        statusBadge.dataset.state = movie.release_status === "COMING_SOON" ? "HELD" : "CONFIRMED";
        const statusCell = element("td");
        statusCell.append(statusBadge);

        const actions = element("td");
        const actWrap = element("div", null, "table-actions");
        const editBtn = element("button", "Sửa", "btn-xs");
        editBtn.type = "button";
        editBtn.onclick = () => populateMovieForm(movie);
        const delBtn = element("button", "Xóa", "btn-xs danger");
        delBtn.type = "button";
        delBtn.onclick = async () => {
            try {
                await api(`/api/admin/movies/${encodeURIComponent(movie.id)}`, { method: "DELETE" });
                await refreshAdminCatalog();
            } catch (error) {
                report("am-feedback", error.message, "ERROR");
            }
        };
        actWrap.append(editBtn, delBtn);
        actions.append(actWrap);

        tr.append(
            titleCell,
            statusCell,
            element("td", `${movie.age_rating} · ★${Number(movie.rating).toFixed(1)}`),
            element("td", String(movie.screening_count || 0)),
            actions,
        );
        return tr;
    }));

    $("as-movie").replaceChildren(...(adminCatalog.movies || []).map((m) => option(m.id, `${m.title} (${m.id})`)));
    $("as-auditorium").replaceChildren(...(adminCatalog.auditoriums || []).map(
        (a) => option(a.id, `${a.name} · ${a.cinema_name} (${a.seat_count} ghế)`),
    ));
    $("aa-cinema").replaceChildren(...(adminCatalog.cinemas || []).map((c) => option(c.id, `${c.name} (${c.city})`)));

    setText("admin-screening-total", String((adminCatalog.screenings || []).length));
    $("admin-screenings-body").replaceChildren(...(adminCatalog.screenings || []).map((slot) => {
        const tr = element("tr");
        const actions = element("td");
        const actWrap = element("div", null, "table-actions");
        const editBtn = element("button", "Sửa", "btn-xs");
        editBtn.type = "button";
        editBtn.onclick = () => {
            $("as-id").value = slot.id;
            $("as-movie").value = slot.movie_id;
            $("as-auditorium").value = slot.auditorium_id;
            $("as-starts").value = toLocalDatetimeValue(slot.starts_at);
            $("as-format").value = slot.format || "2D Phụ đề";
            $("as-price").value = String(slot.base_price);
            $("as-special").checked = Boolean(slot.is_special);
            $("as-id").focus();
        };
        const delBtn = element("button", "Xóa", "btn-xs danger");
        delBtn.type = "button";
        delBtn.onclick = async () => {
            try {
                await api(`/api/admin/screenings/${encodeURIComponent(slot.id)}`, { method: "DELETE" });
                await refreshAdminCatalog();
            } catch (error) {
                report("as-feedback", error.message, "ERROR");
            }
        };
        actWrap.append(editBtn, delBtn);
        actions.append(actWrap);

        tr.append(
            element("td", slot.title),
            element("td", `${slot.cinema_name} · ${slot.auditorium} (${slot.format})`),
            element("td", `${shortTime(slot.starts_at)} · ${formatShortDate.format(new Date(slot.starts_at))}`),
            element("td", formatPrice.format(slot.base_price)),
            actions,
        );
        return tr;
    }));

    $("admin-concessions-body").replaceChildren(...(adminCatalog.concessions || []).map((item) => {
        const tr = element("tr");
        const actions = element("td");
        const actWrap = element("div", null, "table-actions");
        const editBtn = element("button", "Sửa", "btn-xs");
        editBtn.type = "button";
        editBtn.onclick = () => {
            $("ac-id").value = item.id;
            $("ac-name").value = item.name;
            $("ac-price").value = String(item.price);
            $("ac-badge").value = item.badge || "";
            $("ac-desc").value = item.description;
            $("ac-active").checked = item.active !== false;
        };
        const delBtn = element("button", "Xóa", "btn-xs danger");
        delBtn.type = "button";
        delBtn.onclick = async () => {
            try {
                await api(`/api/admin/concessions/${encodeURIComponent(item.id)}`, { method: "DELETE" });
                await refreshAdminCatalog();
            } catch (error) {
                report("ac-feedback", error.message, "ERROR");
            }
        };
        actWrap.append(editBtn, delBtn);
        actions.append(actWrap);
        tr.append(
            element("td", item.name),
            element("td", formatPrice.format(item.price)),
            element("td", item.active === false ? "Ẩn" : "Mở"),
            actions,
        );
        return tr;
    }));

    $("admin-promos-body").replaceChildren(...(adminCatalog.promotions || []).map((promo) => {
        const tr = element("tr");
        const actions = element("td");
        const actWrap = element("div", null, "table-actions");
        const editBtn = element("button", "Sửa", "btn-xs");
        editBtn.type = "button";
        editBtn.onclick = () => {
            $("ap-id").value = promo.id;
            $("ap-tag").value = promo.tag;
            $("ap-code").value = promo.code || "";
            $("ap-type").value = promo.discount_type;
            $("ap-value").value = String(promo.discount_value);
            $("ap-min").value = String(promo.min_amount);
            $("ap-title").value = promo.title;
            $("ap-summary").value = promo.summary;
            $("ap-details").value = promo.details;
            $("ap-active").checked = promo.active !== false;
        };
        const delBtn = element("button", "Xóa", "btn-xs danger");
        delBtn.type = "button";
        delBtn.onclick = async () => {
            try {
                await api(`/api/admin/promotions/${encodeURIComponent(promo.id)}`, { method: "DELETE" });
                await refreshAdminCatalog();
            } catch (error) {
                report("ap-feedback", error.message, "ERROR");
            }
        };
        actWrap.append(editBtn, delBtn);
        actions.append(actWrap);
        const codeDesc = promo.code
            ? `${promo.code} (${promo.discount_type === "PERCENT" ? `${promo.discount_value}%` : formatPrice.format(promo.discount_value)})`
            : "Tin ưu đãi";
        tr.append(element("td", promo.title), element("td", codeDesc), actions);
        return tr;
    }));

    $("admin-blogs-body").replaceChildren(...(adminCatalog.blog_posts || []).map((post) => {
        const tr = element("tr");
        const actions = element("td");
        const actWrap = element("div", null, "table-actions");
        const editBtn = element("button", "Sửa", "btn-xs");
        editBtn.type = "button";
        editBtn.onclick = () => {
            $("ab-id").value = post.id;
            $("ab-cat").value = post.category;
            $("ab-author").value = post.author;
            $("ab-movie").value = post.movie_id || "";
            $("ab-title").value = post.title;
            $("ab-summary").value = post.summary;
            $("ab-content").value = post.content;
        };
        const delBtn = element("button", "Xóa", "btn-xs danger");
        delBtn.type = "button";
        delBtn.onclick = async () => {
            try {
                await api(`/api/admin/blog-posts/${encodeURIComponent(post.id)}`, { method: "DELETE" });
                await refreshAdminCatalog();
            } catch (error) {
                report("ab-feedback", error.message, "ERROR");
            }
        };
        actWrap.append(editBtn, delBtn);
        actions.append(actWrap);
        tr.append(
            element("td", post.title),
            element("td", post.category === "review" ? "Review" : "Blog"),
            actions,
        );
        return tr;
    }));
}

async function loadAdminAccounts() {
    const accounts = await api("/api/admin/accounts");
    $("admin-accounts-body").replaceChildren(...accounts.map((acc) => {
        const tr = element("tr");
        const userCell = element("td");
        userCell.append(element("strong", `@${acc.username}`), element("p", acc.full_name || "Chưa cập nhật tên", "muted"));

        const roleCell = element("td");
        const select = element("select", null, "role-select");
        for (const r of ["USER", "STAFF", "ADMIN"]) {
            const opt = option(r, r);
            if (acc.role === r) opt.selected = true;
            select.append(opt);
        }
        select.disabled = acc.id === currentAccount?.id;
        select.addEventListener("change", async () => {
            select.disabled = true;
            try {
                await api(`/api/admin/accounts/${encodeURIComponent(acc.id)}/role`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ role: select.value }),
                });
            } catch (error) {
                report("admin-status", error.message);
                await loadAdminAccounts();
            } finally {
                select.disabled = acc.id === currentAccount?.id;
            }
        });
        roleCell.append(select);

        tr.append(
            userCell,
            element("td", `${acc.tier?.name || "Member"} · ${acc.points || 0}★`),
            element("td", formatPrice.format(acc.total_spent || 0)),
            roleCell,
        );
        return tr;
    }));
}

async function refreshAdminCatalog() {
    adminCatalog = await api("/api/admin/catalog");
    renderAdminCatalogTables();
}

async function loadAdminView() {
    show("admin-view");
    report("admin-status");
    if (!currentAccount) {
        const { account } = await api("/api/auth/session").catch(() => ({ account: null }));
        currentAccount = account;
    }
    const role = currentAccount?.role;
    if (!role || !["ADMIN", "STAFF"].includes(role)) {
        $("admin-denied").hidden = false;
        $("admin-workspace").hidden = true;
        return;
    }
    $("admin-denied").hidden = true;
    $("admin-workspace").hidden = false;
    setText("admin-role-badge", role);

    const isAdmin = role === "ADMIN";
    document.querySelectorAll("#admin-tablist .movie-tab").forEach((tab) => {
        const tabKey = tab.dataset.adminTab;
        if (!isAdmin && tabKey !== "checkin") tab.hidden = true;
        else tab.hidden = false;
    });

    if (!isAdmin) {
        switchAdminTab("checkin");
        return;
    }

    switchAdminTab(activeAdminTab);
    if (!$("as-starts").value) resetScreeningForm();
    try {
        const [overview] = await Promise.all([
            api("/api/admin/overview"),
            loadAdminBookings(),
            refreshAdminCatalog(),
            loadAdminAccounts(),
        ]);
        renderAdminOverview(overview);
    } catch (error) {
        report("admin-status", error.message);
    }
}

$("admin-refresh-btn").addEventListener("click", () => void loadAdminView());

/* ---------------- ROUTER ---------------- */
window.addEventListener("pageshow", (event) => {
    if (event.persisted && (bookingId || page.has("view"))) location.reload();
});

if (bookingId) {
    show("order");
    void refreshOrder();
} else if (page.has("screening")) {
    ensureCatalogData().then(() => {
        const slot = catalogData.screenings.find(item => item.id === page.get("screening"));
        if (slot) openScreening(slot, null);
        else location.replace("/#lich-chieu");
    }).catch(error => notice(error.message));
} else if (currentView === "movie" && page.get("id")) {
    void loadMovieDetail(page.get("id"));
} else if (currentView === "cinemas") {
    void loadCinemasView();
} else if (currentView === "promotions") {
    void loadPromotionsView();
} else if (currentView === "blog") {
    void loadBlogView();
} else if (currentView === "tickets") {
    show("my-tickets");
    void loadSavedOrders();
    const ticket = page.get("ticket");
    const code = page.get("code");
    if (ticket) void lookupCode(ticket, true);
    else if (code) void lookupCode(code);
} else if (currentView === "account") {
    show("account");
    configureSignIn();
} else if (currentView === "admin") {
    void loadAdminView();
} else {
    show("catalog");
    void loadCatalog();
}
void loadAccount();
setInterval(refreshOrder, 1500);
setInterval(updateTimer, 500);
