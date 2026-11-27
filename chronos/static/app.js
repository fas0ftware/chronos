// Chronos page. Server values are only inserted as text (see ui.js).
"use strict";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
let data = null;

const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
const parseDay = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const longDate = (d) => d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });

// One tooltip for every mark: data-tip holds the text, data-tip-b an optional bold lead.
const tip = () => $("#tip");
function showTip(event) {
  const target = event.target.closest("[data-tip]");
  if (!target) { tip().hidden = true; return; }
  const t = tip();
  t.replaceChildren(el("b", {}, target.dataset.tipB || ""), target.dataset.tipB ? " " : "", target.dataset.tip);
  t.hidden = false;
  const r = target.getBoundingClientRect();
  const w = t.offsetWidth;
  t.style.left = `${Math.max(6, Math.min(window.innerWidth - w - 6, r.left + r.width / 2 - w / 2))}px`;
  t.style.top = `${r.top - t.offsetHeight - 8 < 0 ? r.bottom + 8 : r.top - t.offsetHeight - 8}px`;
}

function stat(label, value, sub, cls) {
  return el("div", { class: "stat" },
    el("div", { class: `stat__value ${cls || ""}` }, value),
    el("div", { class: "stat__label" }, label),
    sub ? el("div", { class: "stat__sub" }, sub) : null);
}

function renderStats(s) {
  const t = s.totals, st = s.streak, w = s.this_week, lw = s.last_week;
  const diff = w.commits - lw.commits;
  $("#stats").replaceChildren(
    stat("commits", t.commits.toLocaleString(), `on ${plural(t.active_days, "day")} in ${plural(t.repos, "project")}`),
    stat("streak", plural(st.current, "day"),
      st.current && !st.today_done ? "nothing yet today" : (st.today_done ? "today counted" : "start one today"),
      st.current && !st.today_done ? "warn" : (st.today_done ? "good" : "")),
    stat("longest streak", plural(st.longest, "day"), st.longest_from ? `${st.longest_from} → ${st.longest_to}` : ""),
    stat("this week", w.commits.toLocaleString(),
      diff === 0 ? "same as last week" : `${Math.abs(diff)} ${diff > 0 ? "more" : "fewer"} than last week (${lw.commits})`),
    stat("today", s.today_commits.toLocaleString(), s.busiest_day ? `busiest day: ${s.busiest_day.commits} on ${s.busiest_day.date}` : ""),
    stat("lines", `+${t.added.toLocaleString()}`, `−${t.deleted.toLocaleString()} removed`),
  );
}

function renderHeatmap(s) {
  const first = parseDay(s.range.from), last = parseDay(s.today);
  const start = addDays(first, -((first.getDay() + 6) % 7));   // Monday of the first week
  const box = $("#heatmap");
  const nodes = ["", "Mon", "", "Wed", "", "Fri", "", ""].map((t) => el("div", { class: "wd" }, t));
  let prevMonth = -1, free = 0, col = 0;
  for (let week = start; week <= last; week = addDays(week, 7), col++) {
    const top = week < first ? first : week;
    let label = "";
    if (top.getMonth() !== prevMonth) {
      prevMonth = top.getMonth();
      if (col >= free) { label = MONTHS[prevMonth]; free = col + 3; }
    }
    nodes.push(el("div", { class: "month" }, label));
    for (let i = 0; i < 7; i++) {
      const d = addDays(week, i);
      if (d < first || d > last) { nodes.push(el("div", {})); continue; }
      const key = isoDay(d);
      const [n, level] = s.days[key] || [0, 0];
      nodes.push(el("div", { class: `cell l${level}`, tabindex: "-1", "data-tip-b": plural(n, "commit"), "data-tip": `on ${longDate(d)}` }));
    }
  }
  box.replaceChildren(...nodes);
  box.style.gridTemplateColumns = `2.2rem repeat(${col}, minmax(10px, 1fr))`;
  box.parentElement.scrollLeft = box.parentElement.scrollWidth;   // newest weeks in view on a phone
  box.setAttribute("aria-label", `${s.totals.commits} commits on ${s.totals.active_days} days between ${s.range.from} and ${s.today}`);
  $("#heat-title").textContent = `Commits per day · ${s.range.from} to ${s.today}`;
}

function renderBars(target, values, label) {
  const max = Math.max(1, ...values);
  target.replaceChildren(...values.map((v, i) => el("div", { class: "hit", "data-tip-b": plural(v, "commit"), "data-tip": label(i) },
    el("span", { class: v ? "" : "zero" }))));
  target.querySelectorAll(".hit > span").forEach((bar, i) => { bar.style.height = `${(values[i] / max) * 100}%`; });
  target.setAttribute("aria-label", values.map((v, i) => `${label(i)}: ${v}`).join(", "));
}

function renderRepos(s) {
  const q = $("#filter").value.trim().toLowerCase();
  const max = Math.max(1, ...s.repos.map((r) => r.commits));
  const rows = s.repos.filter((r) => !q || r.repo.toLowerCase().includes(q)).map((r) => {
    const bar = el("div", { class: "share__bar", "data-tip-b": `${Math.round((r.commits / Math.max(1, s.totals.commits)) * 100)}%`, "data-tip": `of all commits in ${r.repo}` });
    bar.style.width = `${(r.commits / max) * 100}%`;
    return el("tr", {},
      el("td", { class: "name" }, r.repo),
      el("td", { class: "num" }, r.commits.toLocaleString()),
      el("td", { class: "share" }, bar),
      el("td", { class: "num" }, r.active_days),
      el("td", { class: "num lines" }, el("span", { class: "add" }, `+${r.added.toLocaleString()}`), " ", el("span", { class: "del" }, `−${r.deleted.toLocaleString()}`)),
      el("td", { class: "muted" }, new Date(r.last).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })));
  });
  $("#repos").replaceChildren(...(rows.length ? rows : [el("tr", {}, el("td", { colspan: 6, class: "muted" }, "No commits in this period."))]));
}

function renderRecent(s) {
  $("#recent").replaceChildren(...s.recent.map((c) => el("li", {},
    el("span", { class: "when" }, new Date(c.time).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })),
    el("span", { class: "repo" }, c.repo),
    el("span", { class: "subject" }, c.subject))));
}

function render(s) {
  data = s;
  $("#demo").hidden = !s.demo;
  renderStats(s);
  renderHeatmap(s);
  renderBars($("#hours"), s.hours, (h) => `${String(h).padStart(2, "0")}:00–${String(h).padStart(2, "0")}:59`);
  renderBars($("#weekdays"), s.weekdays, (d) => `on ${WEEKDAYS[d]}s`);
  renderRepos(s);
  renderRecent(s);
  $("#updated").textContent = `updated ${new Date().toLocaleTimeString(undefined, { timeStyle: "short" })}`;
}

async function load(force) {
  const days = Number($("#days").value);
  try {
    render(force ? await api("/api/refresh", { days }) : await api(`/api/stats?days=${days}`));
    $("#error").hidden = true;
  } catch (err) {
    $("#error").textContent = `Could not read the commits: ${err.message}`;
    $("#error").hidden = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#days").addEventListener("change", () => load(false));
  $("#refresh").addEventListener("click", () => load(true));
  $("#filter").addEventListener("input", () => data && renderRepos(data));
  document.addEventListener("mouseover", showTip);
  document.addEventListener("scroll", () => { tip().hidden = true; }, true);
  load(false);
  setInterval(() => load(false), 5 * 60 * 1000);
});
