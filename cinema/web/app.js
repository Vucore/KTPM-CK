import { artwork, featuredMovies } from "./films/artwork.js";

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

let movies = [];
let featured = [];
let featuredIndex = 0;
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
let bookingId = new URLSearchParams(location.search).get("booking");
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
    for (const id of ["catalog", "seating", "order"]) $(id).hidden = id !== view;
    $("booking-flow").hidden = view === "catalog";
    $("home-nav").hidden = view !== "catalog";
    $("flow-nav").hidden = view === "catalog";
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

function groupMovies(screenings) {
    const groups = new Map();
    for (const slot of screenings) {
        const key = slot.movie_id ?? JSON.stringify([slot.title, slot.genre, slot.duration_minutes, slot.synopsis]);
        if (!groups.has(key)) {
            groups.set(key, {
                key, title: slot.title, genre: slot.genre, duration: slot.duration_minutes,
                synopsis: slot.synopsis, art: filmArt.get(slot.movie_id ?? slot.title), screenings: [],
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
    setText("featured-synopsis", film.synopsis);
    setText("featured-position", `${featuredIndex + 1} / ${featured.length}`);
    $("featured-controls").hidden = featured.length < 2;
    $("featured").hidden = false;
}

function moveFeatured(offset) {
    featuredIndex = (featuredIndex + offset + featured.length) % featured.length;
    renderFeatured();
}

function option(value, label) {
    return new Option(label, value);
}

function updateQuickScreenings() {
    const film = movies.find((movie) => movie.key === $("quick-film").value);
    const options = film.screenings.map((slot) => {
        const date = formatShortDate.format(new Date(slot.starts_at));
        return option(slot.id, `${shortTime(slot.starts_at)} · ${date} · ${slot.auditorium}`);
    });
    $("quick-screening").replaceChildren(...options);
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
    setText("movie-count", `${cards.length} phim · Suất chiếu demo`);
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
        $("home-nav").querySelector(".primary").href = movies.length ? "#dat-ve" : "#lich-chieu";
        if (!movies.length) {
            setText("catalog-state", "Hiện chưa có suất chiếu sắp tới.");
            $("catalog-state").hidden = false;
            $("featured").hidden = true;
            return;
        }
        featured = featuredMovies.map((id) => movies.find((movie) => movie.art?.id === id)).filter(Boolean);
        if (!featured.length) featured = movies.slice(0, 6);
        featuredIndex = 0;
        renderFeatured();
        $("quick-film").replaceChildren(...movies.map((movie) => option(movie.key, movie.title)));
        $("quick-film").value = featured[0].key;
        updateQuickScreenings();
        $("catalog-state").hidden = true;
    } catch (error) {
        setText("catalog-state", error.message);
        $("home-nav").querySelector(".primary").href = "#lich-chieu";
        $("reload-catalog").hidden = false;
    }
    if (location.hash === "#lich-chieu") $("lich-chieu").scrollIntoView();
}

$("previous-film").addEventListener("click", () => moveFeatured(-1));
$("next-film").addEventListener("click", () => moveFeatured(1));
$("featured-book").addEventListener("click", () => {
    $("quick-film").value = featured[featuredIndex].key;
    updateQuickScreenings();
    $("dat-ve").scrollIntoView();
    $("quick-screening").focus({ preventScroll: true });
});
$("quick-film").addEventListener("change", updateQuickScreenings);
$("schedule-date").addEventListener("change", renderSchedule);
$("movie-search").addEventListener("input", renderSchedule);
$("dat-ve").addEventListener("submit", (event) => {
    event.preventDefault();
    const film = movies.find((movie) => movie.key === $("quick-film").value);
    const slot = film?.screenings.find((item) => item.id === $("quick-screening").value);
    if (slot) openScreening(slot, event.submitter || $("quick-screening"));
});
$("reload-catalog").addEventListener("click", loadCatalog);

function stopSeatUpdates() {
    clearInterval(seatRefresh);
    seatEvents?.close();
    screening = null;
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
    show("seating");
    window.scrollTo(0, 0);
    $("movie-title").focus({ preventScroll: true });
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
        (button || $("seats").querySelector(".seat:not(:disabled)") || $("movie-title")).focus();
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
        bookingId = result.booking.id;
        history.replaceState(null, "", `?booking=${encodeURIComponent(bookingId)}`);
        sessionStorage.removeItem("checkout");
        stopSeatUpdates();
        setBooking(result.booking);
        payment = result.payment;
        show("order");
        renderOrder();
        window.scrollTo(0, 0);
        $("order-heading").focus({ preventScroll: true });
        void refreshOrder();
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

function ticketCard(ticket) {
    const card = element("article", null, "ticket");
    const info = element("div", null, "ticket-info");
    info.append(
        element("p", `Ghế ${ticket.seat}`, "ticket-seat"),
        element("h2", booking.movie_title),
        element("p", screeningLabel(booking)),
    );
    if (ticket.customer_name) info.append(element("p", ticket.customer_name, "ticket-holder"));
    const code = element("div", null, "ticket-code");
    const path = `/api/tickets/${encodeURIComponent(ticket.code)}`;
    const qr = element("img");
    qr.alt = `Mã QR vé ghế ${ticket.seat}`;
    qr.width = 128;
    qr.height = 128;
    qr.src = `${path}/qr.svg`;
    const link = element("a", "Tra cứu vé");
    link.href = path;
    link.setAttribute("aria-label", `Tra cứu vé ghế ${ticket.seat}`);
    code.append(qr, link);
    card.append(info, code);
    return card;
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
    setText("order-seats", booking.seats.join(", "));
    setText("amount", formatPrice.format(booking.amount));
    const status = $("payment-status");
    status.dataset.state = state || "";
    status.hidden = false;
    setText("payment-status", state === "EXPIRED" ? "Đơn đã hết hạn giữ ghế." : paymentLabels[state] || "Đang tải trạng thái thanh toán…");
    $("simulate").hidden = booking.status !== "HELD" || !["PENDING", "DECLINED"].includes(payment?.status);
    updateTimer();
    const signature = tickets.map((ticket) => ticket.code).join(",");
    if (signature !== shownTickets) {
        shownTickets = signature;
        $("tickets").replaceChildren(...tickets.map(ticketCard));
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
        if (missingOrder) setText("order-intro", "Không tìm thấy đơn. Bạn có thể quay lại lịch chiếu.");
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

if (bookingId) {
    show("order");
    void refreshOrder();
} else {
    void loadCatalog();
}
setInterval(refreshOrder, 1500);
setInterval(updateTimer, 500);
