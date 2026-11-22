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
};
const page = new URLSearchParams(location.search);
const signingUp = page.get("mode") === "register";
const accountUpdates = "BroadcastChannel" in window ? new BroadcastChannel("chon-suat.account") : null;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

let movies = [];
let featured = [];
let featuredIndex = 0;
let featuredPlaying = !reducedMotion.matches;
let featuredTimer = null;
let screening = null;
let seatOrigin = null;
let selected = new Set();
let seatRefresh = null;
let seatEvents = null;
let seatRequest = 0;
let seatSignature = null;
let checkoutBusy = false;
let pendingCheckout = false;
let paymentBusy = false;
let paymentRevision = 0;
let booking = null;
let clockOffset = 0;
let payment = null;
let bookingId = page.get("booking");
let loadingOrder = false;
let missingOrder = false;
let shownTickets = "";

function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
}

function setText(id, text) {
    const node = $(id);
    if (node.textContent !== text) node.textContent = text;
}

function notice(text = "") {
    $("notice").hidden = !text;
    setText("notice", text);
}

function showStage(step) {
    for (const id of ["step-seats", "step-payment", "step-tickets"]) {
        if (id === step) $(id).setAttribute("aria-current", "step");
        else $(id).removeAttribute("aria-current");
    }
}

function show(view) {
    for (const id of ["catalog", "seating", "order", "my-tickets", "account"]) $(id).hidden = id !== view;
    $("booking-flow").hidden = view !== "seating" && view !== "order";
    $("quick-book-link").hidden = view !== "catalog";
    syncFeaturedMotion();
    if (view === "my-tickets") $("ticket-history-link").setAttribute("aria-current", "page");
    else $("ticket-history-link").removeAttribute("aria-current");
    if (view === "account") $("account-link").setAttribute("aria-current", "page");
    else $("account-link").removeAttribute("aria-current");
    if (view === "seating") showStage("step-seats");
    if (view === "order") showStage("step-payment");
}

async function api(path, options) {
    let response;
    try {
        response = await fetch(path, { ...options, cache: "no-store" });
    } catch {
        throw new Error("Mất kết nối. Hãy thử lại.");
    }
    const data = await response.json().catch(() => null);
    if (!response.ok) {
        const message = typeof data?.detail === "string" ? data.detail : "Không thể hoàn tất yêu cầu.";
        throw Object.assign(new Error(message), { status: response.status });
    }
    return data;
}

function post(path, input, key) {
    return api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify(input),
    });
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

function screeningLabel(slot) {
    return `${shortTime(slot.starts_at)} · ${dateLabel(slot.starts_at)} · ${slot.auditorium}`;
}

function orderUrl(id) {
    return `/?booking=${encodeURIComponent(id)}`;
}

function report(id, message = "", state = "") {
    const node = $(id);
    node.hidden = !message;
    node.dataset.state = state;
    setText(id, message);
}

function groupMovies(screenings) {
    const groups = new Map();
    for (const slot of screenings) {
        const key = slot.movie_id ?? JSON.stringify([slot.title, slot.genre, slot.duration_minutes, slot.synopsis]);
        if (!groups.has(key)) {
            groups.set(key, {
                key, title: slot.title, genre: slot.genre, duration: slot.duration_minutes,
                art: filmArt.get(slot.movie_id ?? slot.title), screenings: [],
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
        if (film.art.banner) {
            art.srcset = `/assets/films/${film.art.poster} 720w, ${image} 1720w`;
        } else {
            visual.style.setProperty("--featured-image", `url("${image}")`);
        }
        art.addEventListener("error", () => art.remove(), { once: true });
        art.src = image;
        visual.append(art);
    }
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

function option(value, label) {
    return new Option(label, value);
}

function setQuickOptions(id, placeholder, options) {
    const select = $(id);
    select.replaceChildren(option("", placeholder), ...options);
    select.disabled = options.length === 0;
}

function quickFilmScreenings() {
    return movies.find((movie) => movie.key === $("quick-film").value)?.screenings ?? [];
}

function roomKey(slot) {
    return slot.auditorium_id ?? slot.auditorium;
}

function quickRoomScreenings() {
    return quickFilmScreenings().filter((slot) => roomKey(slot) === $("quick-room").value);
}

function updateQuickRooms() {
    const rooms = new Map(quickFilmScreenings().map((slot) => [roomKey(slot), slot.auditorium]));
    setQuickOptions("quick-room", "Chọn phòng", [...rooms].map(([key, label]) => option(key, label)));
    if (rooms.size === 1) $("quick-room").selectedIndex = 1;
    updateQuickDates();
}

function updateQuickDates() {
    const dates = new Map(quickRoomScreenings().map((slot) => [
        dateLabel(slot.starts_at), formatShortDate.format(new Date(slot.starts_at)),
    ]));
    setQuickOptions("quick-date", "Chọn ngày", [...dates].map(([key, label]) => option(key, label)));
    updateQuickScreenings();
}

function updateQuickScreenings() {
    const slots = quickRoomScreenings().filter((slot) => dateLabel(slot.starts_at) === $("quick-date").value);
    setQuickOptions("quick-screening", "Chọn suất", slots.map((slot) => option(slot.id, shortTime(slot.starts_at))));
    updateQuickSubmit();
}

function updateQuickSubmit() {
    $("quick-submit").disabled = !$("quick-screening").value;
}

function movieCard(movie, screenings) {
    const card = element("article", null, "movie-card");
    const poster = element("div", null, "poster");
    poster.setAttribute("aria-hidden", "true");
    poster.append(element("span", null, "brand-mark"));
    if (movie.art) {
        const art = element("img");
        art.alt = "";
        art.loading = "lazy";
        art.decoding = "async";
        art.dataset.film = movie.art.id;
        art.classList.toggle("still", Boolean(movie.art.banner));
        art.addEventListener("error", () => art.remove(), { once: true });
        art.src = `/assets/films/${movie.art.poster}`;
        poster.append(art);
    }

    const info = element("div", null, "movie-info");
    const schedule = element("div", null, "showtimes");
    const days = new Map();
    for (const slot of screenings) {
        const day = dateLabel(slot.starts_at);
        if (!days.has(day)) {
            const group = element("div");
            const times = element("div", null, "showtime-list");
            group.append(element("p", day, "showtime-day"), times);
            schedule.append(group);
            days.set(day, times);
        }
        const time = shortTime(slot.starts_at);
        const button = element("button", `${time} · ${slot.auditorium}`, "showtime");
        button.type = "button";
        button.setAttribute("aria-label", `Chọn ghế cho ${movie.title}, ${screeningLabel(slot)}`);
        button.addEventListener("click", () => openScreening(slot, button));
        days.get(day).append(button);
    }
    info.append(
        element("h3", movie.title),
        element("p", `${movie.genre} · ${movie.duration} phút`, "movie-meta"),
        schedule,
    );
    card.append(poster, info);
    return card;
}

function searchText(value) {
    return value.toLocaleLowerCase("vi-VN").normalize("NFD").replace(/\p{M}/gu, "").replaceAll("đ", "d").trim();
}

function renderSchedule() {
    const date = $("schedule-date").value;
    const query = searchText($("movie-search").value);
    const cards = [];
    for (const film of movies) {
        if (query && !searchText(film.title).includes(query)) continue;
        const slots = date ? film.screenings.filter((slot) => dateLabel(slot.starts_at) === date) : film.screenings;
        if (slots.length) cards.push(movieCard(film, slots));
    }
    $("screenings").replaceChildren(...cards);
    setText("movie-count", `${cards.length} phim`);
    $("catalog-state").hidden = cards.length > 0 || !movies.length;
    if (!cards.length && movies.length) setText("catalog-state", "Không tìm thấy phim phù hợp. Hãy đổi tên phim hoặc ngày chiếu.");
}

async function loadCatalog() {
    $("reload-catalog").hidden = true;
    $("catalog-state").hidden = false;
    setText("catalog-state", "Đang tải lịch chiếu…");
    try {
        const screenings = await api("/api/screenings");
        movies = groupMovies(screenings);
        const dates = new Map(screenings.map((slot) => [
            dateLabel(slot.starts_at), formatShortDate.format(new Date(slot.starts_at)),
        ]));
        $("schedule-filters").hidden = !movies.length;
        $("date-filter").hidden = dates.size < 2;
        $("movie-search").value = "";
        $("schedule-date").replaceChildren(option("", "Tất cả ngày"), ...[...dates].map(([key, label]) => option(key, label)));
        renderSchedule();
        $("movie-count").hidden = !movies.length;
        $("dat-ve").hidden = !movies.length;
        $("quick-book-link").href = movies.length ? "#dat-ve" : "#lich-chieu";
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
        setQuickOptions("quick-film", "Chọn phim", movies.map((movie) => option(movie.key, movie.title)));
        updateQuickRooms();
        $("catalog-state").hidden = true;
    } catch (error) {
        setText("catalog-state", error.message);
        $("quick-book-link").href = "#lich-chieu";
        $("reload-catalog").hidden = false;
    }
    if (location.hash === "#lich-chieu") $("lich-chieu").scrollIntoView();
}

$("previous-film").addEventListener("click", () => {
    setFeaturedPlaying(false);
    moveFeatured(-1);
});
$("next-film").addEventListener("click", () => {
    setFeaturedPlaying(false);
    moveFeatured(1);
});
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
$("quick-film").addEventListener("change", updateQuickRooms);
$("quick-room").addEventListener("change", updateQuickDates);
$("quick-date").addEventListener("change", updateQuickScreenings);
$("quick-screening").addEventListener("change", updateQuickSubmit);
$("schedule-date").addEventListener("change", renderSchedule);
$("movie-search").addEventListener("input", renderSchedule);
$("dat-ve").addEventListener("submit", (event) => {
    event.preventDefault();
    const slot = quickRoomScreenings().find((item) => item.id === $("quick-screening").value);
    if (slot) openScreening(slot, event.submitter || $("quick-screening"));
});
$("reload-catalog").addEventListener("click", loadCatalog);

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
    seatOrigin = origin;
    selected = new Set();
    pendingCheckout = false;
    seatSignature = null;
    $("customer").value = "";
    $("reload-seats").hidden = true;
    $("seats").replaceChildren(element("p", "Đang tải sơ đồ ghế…", "seat-message"));
    setText("seat-availability", "");
    setText("movie-title", slot.title);
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
    if (!id || checkoutBusy || pendingCheckout) return;
    const request = ++seatRequest;
    try {
        const seats = await api(`/api/screenings/${encodeURIComponent(id)}/seats`);
        if (screening?.id !== id || request !== seatRequest || checkoutBusy || pendingCheckout) return;
        $("reload-seats").hidden = true;
        const signature = JSON.stringify(seats);
        if (signature === seatSignature) return;
        seatSignature = signature;
        renderSeats(seats);
    } catch (error) {
        if (screening?.id !== id || request !== seatRequest || checkoutBusy || pendingCheckout) return;
        if (!seatSignature) {
            $("seats").replaceChildren(element("p", error.message, "seat-message"));
            $("reload-seats").hidden = false;
        }
    }
}

function orderedSelection() {
    return [...selected].sort(seatOrder.compare);
}

function renderSelection() {
    $("selection").replaceChildren(...(selected.size
        ? orderedSelection().map((label) => element("span", label, "seat-chip"))
        : ["Chưa chọn ghế"]));
    const hold = $("hold");
    hold.disabled = checkoutBusy || !selected.size;
    const label = checkoutBusy ? "Đang giữ ghế…" : pendingCheckout ? "Thử giữ ghế lại" : "Giữ ghế và tiếp tục";
    setText("hold", label);
    $("customer").disabled = checkoutBusy || pendingCheckout;
    $("checkout").setAttribute("aria-busy", String(checkoutBusy));
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
        button.setAttribute("aria-label", `${seat.label}, ${status}${premium ? ", cao cấp" : ""}`);
        button.classList.toggle("premium", premium);
        button.classList.toggle("unavailable", button.disabled);
        function update() {
            const pressed = selected.has(seat.label);
            button.classList.toggle("selected", pressed);
            button.setAttribute("aria-pressed", String(pressed));
        }
        update();
        button.addEventListener("click", () => {
            if (checkoutBusy || pendingCheckout) return;
            if (selected.has(seat.label)) selected.delete(seat.label);
            else if (selected.size < 8) selected.add(seat.label);
            else return notice("Mỗi đơn giữ tối đa 8 ghế.");
            notice();
            update();
            renderSelection();
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
    stopSeatUpdates();
    notice();
    show("catalog");
    seatOrigin?.focus();
});

$("checkout").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (checkoutBusy || !selected.size) return;
    const payload = {
        screening_id: screening.id, seats: orderedSelection(), customer_name: $("customer").value.trim() || null,
    };
    checkoutBusy = true;
    $("back").disabled = true;
    renderSelection();
    notice();
    try {
        const result = await post("/api/checkout", payload, requestKey("checkout", payload));
        sessionStorage.removeItem("checkout");
        stopSeatUpdates();
        payment = result.payment;
        openOrder(result.booking);
    } catch (error) {
        pendingCheckout = !error.status || error.status >= 500;
        notice(pendingCheckout ? `${error.message} Bấm “Thử giữ ghế lại” để tiếp tục yêu cầu.` : error.message);
        if (!pendingCheckout) sessionStorage.removeItem("checkout");
    } finally {
        checkoutBusy = false;
        $("back").disabled = false;
        renderSelection();
        if (!bookingId && !pendingCheckout) void refreshSeats();
    }
});

function updateTimer() {
    if (!booking) return;
    const remaining = Math.max(0, Math.ceil((Date.parse(booking.expires_at) - Date.now() - clockOffset) / 1000));
    const minutes = Math.floor(remaining / 60);
    const seconds = String(remaining % 60).padStart(2, "0");
    $("timer").hidden = booking.status !== "HELD";
    setText("timer", remaining ? `Giữ ghế còn ${minutes}:${seconds}` : "Đang cập nhật thời hạn giữ ghế…");
    $("pay").disabled = paymentBusy || remaining === 0;
    $("outcome").disabled = paymentBusy;
    $("delay").disabled = paymentBusy;
    $("simulate").setAttribute("aria-busy", String(paymentBusy));
    setText("pay", paymentBusy ? "Đang gửi thanh toán…" : payment?.status === "DECLINED" ? "Thử thanh toán lại" : "Chạy thanh toán");
}

function setBooking(value) {
    booking = value;
    clockOffset = Date.parse(value.server_now) - Date.now();
}

function openOrder(value) {
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
        element("p", screeningLabel(details)),
    );
    if (ticket.customer_name) info.append(element("p", ticket.customer_name, "ticket-holder"));
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
    setText("order-code", booking.id);
}

function renderOrder() {
    const confirmed = booking.status === "CONFIRMED";
    const expired = booking.status === "EXPIRED";
    const tickets = booking.tickets || [];
    const refunded = payment?.status === "REFUNDED";
    const state = expired && !refunded ? "EXPIRED" : payment?.status;
    $("order-tools").hidden = confirmed;
    $("order-summary").hidden = false;
    $("retry-booking").hidden = !expired;
    $("ticket-return").hidden = !confirmed;
    $("order-intro").hidden = !confirmed;
    showStage(confirmed ? "step-tickets" : "step-payment");
    setText("order-heading", confirmed ? "Vé của bạn" : "Thanh toán");
    if (confirmed) setText("order-intro", `${tickets.length} vé điện tử · Đặt vé thành công`);
    setText("order-title", booking.movie_title);
    setText("order-details", screeningLabel(booking));
    renderBookingPoster("order-poster", booking.movie_title);
    setText("order-seats", booking.seats.join(", "));
    setText("amount", formatPrice.format(booking.amount));
    const status = $("payment-status");
    status.dataset.state = state || "";
    status.hidden = false;
    setText("payment-status", state === "EXPIRED" ? "Đơn đã hết hạn giữ ghế." : paymentLabels[state] || "Đang tải trạng thái thanh toán…");
    $("simulate").hidden = booking.status !== "HELD" || !["PENDING", "DECLINED"].includes(payment?.status);
    updateTimer();
    renderOrderAccess();
    const signature = tickets.map((ticket) => ticket.code).join(",");
    if (signature !== shownTickets) {
        shownTickets = signature;
        $("tickets").replaceChildren(...tickets.map((ticket) => ticketCard(ticket, booking)));
    }
}

async function refreshOrder() {
    if (!bookingId || missingOrder || loadingOrder || paymentBusy || booking?.tickets?.length) return;
    loadingOrder = true;
    const revision = paymentRevision;
    const path = `/api/bookings/${encodeURIComponent(bookingId)}`;
    try {
        setBooking(await api(path));
        renderOrder();
        if (booking.status !== "CONFIRMED" && payment?.status !== "REFUNDED") {
            const nextPayment = await api(`${path}/payment`);
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

function savedOrderRow(order) {
    const row = element("li", null, "history-row");
    const info = element("div", null, "history-info");
    const state = element("span", bookingLabels[order.status] || "Kiểm tra trạng thái", "history-state");
    state.dataset.state = order.status;
    info.append(
        state,
        element("h3", order.movie_title),
        element("p", screeningLabel(order), "muted"),
        element("p", `Ghế ${order.seats.join(", ")}`, "history-seats"),
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
            ? "Các đơn được đồng bộ theo tài khoản của bạn."
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

function configureSignIn() {
    if (!signingUp) return;
    setText("auth-form-title", "Tạo tài khoản");
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

async function loadAccount() {
    const showingAccount = !$("account").hidden;
    if (showingAccount) {
        $("reload-account").hidden = true;
        report("account-status", "Đang tải thông tin tài khoản…");
    }
    try {
        const { account } = await api("/api/auth/session");
        setText("account-link", account ? "Tài khoản" : "Đăng nhập");
        if (showingAccount) {
            $("sign-in").hidden = Boolean(account);
            $("account-profile").hidden = !account;
            if (account) setText("account-username", account.username);
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
        // Signing in still works in browsers that block web storage.
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
        location.replace("/?view=tickets");
    } catch (error) {
        const message = error.status === 422 ? "Hãy kiểm tra định dạng tên đăng nhập và độ dài mật khẩu." : error.message;
        report("auth-status", message, "ERROR");
        button.disabled = false;
    }
});

$("sign-out").addEventListener("click", async () => {
    const button = $("sign-out");
    button.disabled = true;
    report("logout-status", "Đang đăng xuất…");
    try {
        await api("/api/auth/logout", { method: "POST" });
        accountChanged();
        accountUpdates?.postMessage("changed");
        location.replace("/?view=account");
    } catch (error) {
        report("logout-status", error.message, "ERROR");
        button.disabled = false;
    }
});

$("reload-account").addEventListener("click", loadAccount);

window.addEventListener("pageshow", (event) => {
    if (event.persisted && (bookingId || page.has("view"))) location.reload();
});

if (bookingId) {
    show("order");
    void refreshOrder();
} else if (page.get("view") === "tickets") {
    show("my-tickets");
    void loadSavedOrders();
    const ticket = page.get("ticket");
    const code = page.get("code");
    if (ticket) void lookupCode(ticket, true);
    else if (code) void lookupCode(code);
} else if (page.get("view") === "account") {
    show("account");
    configureSignIn();
} else {
    void loadCatalog();
}
void loadAccount();
setInterval(refreshOrder, 1500);
setInterval(updateTimer, 500);
