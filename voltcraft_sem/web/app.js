"use strict";
const $ = id => document.getElementById(id);

let rangeMin = 60;
let currency = "€";
let canControl = false;
let suppressToggle = false;   // ignore change events we set programmatically

/* ---------- toasts ---------- */
function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.textContent = msg;
  $("toasts").appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; setTimeout(() => t.remove(), 250); }, 3200);
}

const fmt = (x, d = 1) => (x == null || isNaN(x)) ? "—" : Number(x).toFixed(d);
const hhmm = v => { const d = new Date(v);
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };

/* ---------- chart ---------- */
let chart = null;
try {
  chart = new Chart($("chart"), {
    type: "line",
    data: { datasets: [{ label: "W", data: [], borderColor: "#f5b942",
      backgroundColor: "rgba(245,185,66,.12)", fill: true, pointRadius: 0,
      tension: .25, borderWidth: 2 }] },
    options: { animation: false, parsing: false, maintainAspectRatio: false,
      scales: {
        x: { type: "linear", ticks: { color: "#8b93a7", maxTicksLimit: 8, callback: hhmm },
             grid: { color: "#222838" } },
        y: { beginAtZero: true, ticks: { color: "#8b93a7" }, grid: { color: "#222838" } } },
      plugins: { legend: { display: false },
        tooltip: { callbacks: { title: it => hhmm(it[0].parsed.x),
          label: it => it.parsed.y.toFixed(2) + " W" } } } }
  });
} catch (e) { console.error("chart init failed (live values still work):", e); }

/* ---------- status poll ---------- */
async function poll() {
  try {
    const s = await (await fetch("/api/status")).json();
    currency = s.currency || currency;
    canControl = !!s.can_control;

    // connection pill
    const pill = $("pill"), txt = $("pillText");
    const map = { connected: ["ok", "Connected"], connecting: ["warn", "Connecting…"],
      scanning: ["warn", "Scanning…"], reconnecting: ["warn", "Reconnecting…"],
      starting: ["warn", "Starting…"], stopped: ["bad", "Stopped"] };
    const [cls, label] = map[s.state] || ["bad", s.state || "—"];
    pill.className = "pill " + cls;
    txt.textContent = label;

    // device line
    const d = s.device || {};
    $("device").textContent = d.address
      ? `${d.name || "device"} · ${d.address}${d.rssi != null ? " · " + d.rssi + " dBm" : ""}`
      : (s.error || "Searching for device…");

    // metrics
    const m = s.latest;
    if (m) {
      $("w").textContent = fmt(m.w, 1);
      $("v").textContent = fmt(m.v, 1);
      $("a").textContent = fmt(m.a, 3);
      $("pf").textContent = fmt(m.pf, 3);
      $("hz").textContent = fmt(m.hz, 2);
      const on = m.state === 1;
      const b = $("badge");
      b.textContent = on ? "ON" : (m.state === 2 ? "TIMER" : "OFF");
      b.className = "state-badge " + (on ? "state-on" : "state-off");
      if (!suppressToggle) $("toggle").checked = on;
    }
    if (s.cost_per_hour != null)
      $("costRate").textContent = currency + fmt(s.cost_per_hour, 3) + " /h";
    $("costNow").textContent = s.cost_per_hour != null ? currency + fmt(s.cost_per_hour, 3) : "—";

    // control availability
    const tg = $("toggle");
    tg.disabled = !canControl;
    $("controlHint").textContent = s.connected && !canControl
      ? "Monitor only — pass --mac to enable control" : "";
    $("switchWrap").title = tg.disabled ? "Control unavailable" : "Toggle the socket";
  } catch (e) {
    $("pill").className = "pill bad";
    $("pillText").textContent = "No server";
  }
}

/* ---------- history poll ---------- */
async function loadHistory() {
  try {
    const h = await (await fetch(`/api/history?minutes=${rangeMin}`)).json();
    currency = h.currency || currency;
    if (chart) {
      chart.data.datasets[0].data = h.points.map(p => ({ x: p.ts * 1000, y: p.w }));
      chart.update("none");
    }
    $("kwhToday").textContent = fmt(h.energy_kwh_today, 3);
    $("costToday").textContent = currency + fmt(h.cost_today, 2);
    $("rangeEnergy").textContent =
      `This range: ${fmt(h.energy_kwh_range, 3)} kWh · ${currency}${fmt(h.cost_range, 2)}`;
  } catch (e) { /* ignore transient */ }
}

/* ---------- config (price) ---------- */
async function loadConfig() {
  try {
    const c = await (await fetch("/api/config")).json();
    $("price").value = c.price_per_kwh;
    $("currency").value = c.currency;
    currency = c.currency;
  } catch (e) { /* ignore */ }
}

$("savePrice").onclick = async () => {
  const price = parseFloat($("price").value);
  const cur = $("currency").value.trim() || "€";
  try {
    const r = await fetch("/api/config", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ price_per_kwh: price, currency: cur }) });
    if (!r.ok) throw new Error(await r.text());
    currency = cur;
    toast("Price saved", "ok");
    loadHistory();
  } catch (e) { toast("Save failed: " + e.message, "err"); }
};

/* ---------- toggle ---------- */
$("toggle").onchange = async (e) => {
  const on = e.target.checked;
  suppressToggle = true;
  try {
    const r = await (await fetch("/api/switch", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on }) })).json();
    if (!r.ok) { e.target.checked = !on; toast("Switch failed: " + (r.error || "?"), "err"); }
    else toast("Socket turned " + (on ? "ON" : "OFF"), "ok");
  } catch (err) { e.target.checked = !on; toast("Network error", "err"); }
  finally { setTimeout(() => { suppressToggle = false; poll(); }, 800); }
};

/* ---------- rescan ---------- */
$("rescan").onclick = async () => {
  try { await fetch("/api/rescan", { method: "POST" }); toast("Rescanning for device…"); }
  catch (e) { toast("Rescan failed", "err"); }
};

/* ---------- range buttons ---------- */
$("ranges").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  rangeMin = parseInt(b.dataset.min, 10);
  [...$("ranges").children].forEach(c => c.classList.toggle("active", c === b));
  loadHistory();
});

/* ---------- boot ---------- */
loadConfig(); poll(); loadHistory();
setInterval(poll, 2000);
setInterval(loadHistory, 10000);
