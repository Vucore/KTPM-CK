const $ = (id) => document.getElementById(id);
const formatDate = new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Ho_Chi_Minh",
});
const formatPrice = new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" });
const paymentLabels = {
    PENDING: "Chưa thanh toán",
    PROCESSING: "Đang chờ kết quả thanh toán",
    DECLINED: "Thanh toán bị từ chối. Bạn có thể thử lại trong thời hạn giữ ghế.",
    SUCCEEDED: "Thanh toán thành công. Đang đồng bộ với đơn đặt vé.",
    REFUNDED: "Đã hoàn tiền do đơn hết hạn.",
};

let screening = null;
let selected = new Set();
let seatRefresh = null;
let seatEvents = null;
let seatRequest = 0;
let seatSignature = null;
let checkoutBusy = false;
let pendingCheckout = false;
let paymentBusy = false;
let booking = null;
let clockOffset = 0;
let payment = null;
let bookingId = new URLSearchParams(location.search).get("booking");
let loadingOrder = false;
let shownTickets = "";

function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
}

function notice(text = "") {
    $("notice").textContent = text;
    $("notice").hidden = !text;
}

function show(view) {
    for (const id of ["catalog", "seating", "order"]) $(id).hidden = id !== view;
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

async function loadCatalog() {
    notice();
    $("reload-catalog").hidden = true;
    $("screenings").replaceChildren(element("p", "Đang tải suất chiếu…"));
    try {
        const screenings = await api("/api/screenings");
        $("screenings").replaceChildren(...screenings.map((movie) => {
            const card = element("button", null, "panel screening");
            card.type = "button";
            card.append(
                element("span", `${movie.genre} · ${movie.duration_minutes} phút`, "meta"),
                element("strong", movie.title),
                element("p", movie.synopsis),
                element("span", `${formatDate.format(new Date(movie.starts_at))} · ${movie.auditorium}`, "time"),
            );
            card.addEventListener("click", () => openScreening(movie));
            return card;
        }));
        if (!screenings.length) $("screenings").append(element("p", "Hiện chưa có suất chiếu sắp tới."));
    } catch (error) {
        $("screenings").replaceChildren();
        $("reload-catalog").hidden = false;
        notice(error.message);
    }
}

function stopSeatUpdates() {
    clearInterval(seatRefresh);
    seatEvents?.close();
    screening = null;
}

function openScreening(movie) {
    stopSeatUpdates();
    screening = movie;
    selected = new Set();
    pendingCheckout = false;
    seatSignature = null;
    $("seats").replaceChildren(element("p", "Đang tải sơ đồ ghế…"));
    $("movie-title").textContent = movie.title;
    $("movie-details").textContent = `${formatDate.format(new Date(movie.starts_at))} · ${movie.auditorium}`;
    show("seating");
    renderSelection();
    notice();
    void refreshSeats();
    seatEvents = new EventSource(`/api/screenings/${encodeURIComponent(movie.id)}/updates`);
    seatEvents.onmessage = () => refreshSeats();
    seatRefresh = setInterval(refreshSeats, 5000);
}

async function refreshSeats() {
    const id = screening?.id;
    if (!id || checkoutBusy || pendingCheckout) return;
    const request = ++seatRequest;
    try {
        const seats = await api(`/api/screenings/${encodeURIComponent(id)}/seats`);
        if (screening?.id !== id || request !== seatRequest || checkoutBusy || pendingCheckout) return;
        const signature = JSON.stringify(seats);
        if (signature === seatSignature) return;
        seatSignature = signature;
        renderSeats(seats);
    } catch (error) {
        if (screening?.id === id && request === seatRequest) notice(error.message);
    }
}

function renderSelection() {
    $("selection").textContent = selected.size ? [...selected].sort().join(", ") : "Chưa chọn ghế";
    $("hold").disabled = checkoutBusy || !selected.size;
}

function renderSeats(seats) {
    const focus = document.activeElement?.dataset.seat;
    const rows = new Map();
    for (const seat of seats) {
        const row = seat.label.match(/^[A-Z]+/)[0];
        if (!rows.has(row)) rows.set(row, element("div", null, "seat-row"));
        const button = element("button", seat.label, "seat");
        button.type = "button";
        button.dataset.seat = seat.label;
        button.disabled = seat.status !== "AVAILABLE";
        if (button.disabled && selected.delete(seat.label)) notice("Ghế bạn chọn vừa được giữ hoặc bán.");
        const status = seat.status === "SOLD" ? "Đã bán" : seat.status === "HELD" ? "Đang giữ" : "Trống";
        button.setAttribute("aria-label", `${seat.label}, ${status}${seat.seat_type === "PREMIUM" ? ", cao cấp" : ""}`);
        button.classList.toggle("premium", seat.seat_type === "PREMIUM");
        button.classList.toggle("unavailable", button.disabled);
        function update() {
            button.classList.toggle("selected", selected.has(seat.label));
            button.setAttribute("aria-pressed", String(selected.has(seat.label)));
        }
        update();
        button.addEventListener("click", () => {
            if (checkoutBusy) return;
            if (selected.has(seat.label)) selected.delete(seat.label);
            else if (selected.size < 8) selected.add(seat.label);
            else return notice("Mỗi đơn giữ tối đa 8 ghế.");
            notice();
            update();
            renderSelection();
        });
        rows.get(row).append(button);
    }
    $("seats").replaceChildren(...rows.values());
    if (focus) $("seats").querySelector(`[data-seat="${focus}"]`)?.focus();
    renderSelection();
}

$("checkout").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (checkoutBusy || !selected.size) return;
    const payload = {
        screening_id: screening.id, seats: [...selected].sort(), customer_name: $("customer").value.trim() || null,
    };
    checkoutBusy = true;
    $("back").disabled = true;
    $("customer").disabled = true;
    renderSelection();
    notice();
    try {
        const result = await post("/api/checkout", payload, requestKey("checkout", payload));
        bookingId = result.booking.id;
        history.replaceState(null, "", `?booking=${bookingId}`);
        sessionStorage.removeItem("checkout");
        stopSeatUpdates();
        setBooking(result.booking);
        payment = result.payment;
        show("order");
        renderOrder();
        void refreshOrder();
    } catch (error) {
        notice(error.message);
        pendingCheckout = !error.status || error.status >= 500;
        if (!pendingCheckout) sessionStorage.removeItem("checkout");
    } finally {
        checkoutBusy = false;
        $("back").disabled = false;
        $("customer").disabled = false;
        renderSelection();
        // Keep the selection after a network error so a retry uses the same key.
        if (!bookingId && !pendingCheckout) void refreshSeats();
    }
});

function updateTimer() {
    if (!booking) return;
    const remaining = Math.max(0, Math.ceil((Date.parse(booking.expires_at) - Date.now() - clockOffset) / 1000));
    $("timer").textContent = booking.status === "HELD"
        ? `Giữ ghế còn ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}`
        : booking.status === "EXPIRED" ? "Đơn đã hết hạn giữ ghế" : "";
    $("pay").disabled = paymentBusy || remaining === 0;
}

function setBooking(value) {
    booking = value;
    clockOffset = Date.parse(value.server_now) - Date.now();
}

function renderOrder() {
    $("order-heading").textContent = booking.status === "CONFIRMED" ? "Vé của bạn" : "Thanh toán";
    $("order-title").textContent = booking.movie_title;
    $("order-details").textContent = `${formatDate.format(new Date(booking.starts_at))} · ${booking.auditorium} · Ghế ${booking.seats.join(", ")}`;
    $("amount").textContent = formatPrice.format(booking.amount);
    $("payment-status").textContent = booking.status === "CONFIRMED"
        ? "Đã xác nhận đặt vé."
        : paymentLabels[payment?.status] || "Đang tải trạng thái thanh toán…";
    $("simulate").hidden = booking.status !== "HELD" || !["PENDING", "DECLINED"].includes(payment?.status);
    updateTimer();
    const tickets = booking.tickets || [];
    const signature = tickets.map((ticket) => ticket.code).join(",");
    if (signature !== shownTickets) {
        shownTickets = signature;
        $("tickets").replaceChildren(...tickets.map((ticket) => {
            const card = element("article", null, "panel ticket");
            const qr = element("img");
            qr.alt = `Mã QR vé ghế ${ticket.seat}`;
            qr.src = `/api/tickets/${ticket.code}/qr.svg`;
            const link = element("a", "Tra cứu vé");
            link.href = `/api/tickets/${ticket.code}`;
            card.append(element("h2", `Ghế ${ticket.seat}`), element("p", ticket.customer_name || "Vé điện tử"), qr, link);
            return card;
        }));
    }
}

async function refreshOrder() {
    if (!bookingId || loadingOrder || booking?.status === "CONFIRMED" && booking.tickets?.length) return;
    loadingOrder = true;
    try {
        setBooking(await api(`/api/bookings/${encodeURIComponent(bookingId)}`));
        renderOrder();
        if (booking.status !== "CONFIRMED" && payment?.status !== "REFUNDED") {
            payment = await api(`/api/bookings/${encodeURIComponent(bookingId)}/payment`);
            renderOrder();
        }
        if (!$("reload-order").hidden) notice();
        $("reload-order").hidden = true;
    } catch (error) {
        $("reload-order").hidden = false;
        notice(error.message);
    } finally {
        loadingOrder = false;
    }
}

$("simulate").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (paymentBusy) return;
    const payload = { outcome: $("outcome").value, delay_seconds: Number($("delay").value) };
    const slot = `payment-${bookingId}`;
    paymentBusy = true;
    updateTimer();
    notice();
    try {
        payment = await post(`/api/bookings/${bookingId}/payment/simulate`, payload, requestKey(slot, payload));
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

$("back").addEventListener("click", () => {
    stopSeatUpdates();
    notice();
    show("catalog");
});
$("reload-catalog").addEventListener("click", loadCatalog);
$("reload-order").addEventListener("click", refreshOrder);

if (bookingId) {
    show("order");
    void refreshOrder();
}
else void loadCatalog();
setInterval(refreshOrder, 1500);
setInterval(updateTimer, 500);
