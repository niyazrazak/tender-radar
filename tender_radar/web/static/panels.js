"use strict";

/** Detail panel for one lead, with the triage buttons. */
const drawer = {
  lead: null,
  showOriginal: false,

  show(lead) {
    if (!lead) return;
    if (this.lead !== lead) this.showOriginal = false;
    this.lead = lead;
    this.refresh();
    $("drawer").classList.add("open");
    $("drawer").setAttribute("aria-hidden", "false");
    $("scrim").classList.add("open");
  },

  refresh() {
    const lead = this.lead;
    if (!lead) return;
    const translated = lead.title_en && lead.title_en !== lead.title;
    const brief = this.showOriginal ? lead.brief : lead.brief_en || lead.brief;
    const activities = this.showOriginal ? lead.activities : lead.activities_en || lead.activities;
    const hasOriginal = lead.brief_en && lead.brief_en !== lead.brief;
    $("drawerBody").innerHTML = `
      <div class="drawer-head">
        <span>${esc(SOURCE_LABELS[lead.source] || lead.source)} · score ${lead.score}</span>
        <button class="icon-btn" data-close aria-label="Close">
          <svg viewBox="0 0 20 20"><path d="m5 5 10 10M15 5 5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </button>
      </div>
      <div>
        <h2 dir="auto">${esc(lead.title_en || lead.title)}</h2>
        ${translated ? `<div class="original" dir="rtl">${esc(lead.title)}</div>` : ""}
      </div>
      <div class="actions">
        <a class="btn primary" href="${esc(lead.url)}" target="_blank" rel="noopener">Open on portal
          <svg viewBox="0 0 20 20"><path d="M8 4H4v12h12v-4M11 3h6v6M17 3l-8 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></a>
        <div class="seg">${["shortlisted", "bidding", "dismissed"].map((s) =>
          `<button data-state="${s}" class="${lead.lead_status === s ? "on" : ""}">${STATE_LABELS[s]}</button>`).join("")}</div>
      </div>
      <dl class="facts">${facts(lead)}</dl>
      ${chips(lead.matched) ? `<div class="block"><h4>Matched keywords</h4>${chips(lead.matched)}</div>` : ""}
      ${activities ? `<div class="block"><h4>Activities</h4><p dir="auto">${esc(activities)}</p></div>` : ""}
      ${brief ? `<div class="block"><h4>Brief ${hasOriginal ? `<button class="toggle-lang" data-lang>${this.showOriginal ? "Show English" : "Show original"}</button>` : ""}</h4>
        <p dir="auto">${esc(brief)}</p></div>` : ""}`;
  },

  close() {
    $("drawer").classList.remove("open");
    $("drawer").setAttribute("aria-hidden", "true");
    $("scrim").classList.remove("open");
  },

  isOpen() {
    return $("drawer").classList.contains("open");
  },

  bind(app) {
    $("scrim").addEventListener("click", () => this.close());
    $("drawerBody").addEventListener("click", (e) => {
      if (e.target.closest("[data-close]")) this.close();
      const state = e.target.closest("[data-state]");
      if (state) app.setState(this.lead, state.dataset.state);
      if (e.target.closest("[data-lang]")) { this.showOriginal = !this.showOriginal; this.refresh(); }
    });
  },
};

function facts(lead) {
  const left = daysLeft(lead.closing, todayISO());
  const money = (value) => (value ? `${esc(value)} ${esc(lead.currency)}` : "");
  const rows = [
    ["Buyer", `<span dir="auto">${esc(lead.buyer_en || lead.buyer)}</span>`],
    ["Country", esc(lead.country)],
    ["Reference", esc(lead.ref_no)],
    ["Status", esc(lead.status)],
    ["Type", esc(lead.tender_type)],
    ["Category", `<span dir="auto">${esc(lead.category_en || lead.category)}</span>`],
    ["Published", lead.published ? fmtDate(lead.published) : ""],
    ["Closing", lead.closing ? `${fmtDate(lead.closing)}${left !== null && left >= 0 ? ` · ${left} days left` : ""}` : ""],
    ["Document fee", esc(fmtFee(lead)) || "Not listed"],
    ["Bid bond", esc(fmtBond(lead)) || "Not listed"],
    ["Winner", `<span dir="auto">${esc((lead.extra?.winners || []).map((w) => w.company).join("; "))}</span>`],
    ["Award value", money(lead.extra?.award_value)],
    ["Bidders", lead.extra?.bidders ? esc(lead.extra.bidders) : ""],
    ["First seen", esc(lead.first_seen.slice(0, 10))],
  ];
  return rows.filter(([, v]) => v && v !== "<span dir=\"auto\"></span>")
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

/** The status dot in the header and the "recent checks" popover. */
const runPanel = {
  status: null,

  update(status) {
    this.status = status;
    const sched = status.scheduler;
    const last = status.runs.find((r) => r.status !== "running");
    $("runNow").disabled = sched.running;
    $("runDot").className = `dot ${sched.running ? "running" : last ? last.status : ""}`;
    $("runText").textContent = sched.running
      ? `Checking portals… ${ago(sched.running_since, true)}`
      : last ? `Checked ${ago(last.finished)} · next ${clock(sched.next_run)}` : `First check ${clock(sched.next_run)}`;
    if (!$("activity").hidden) this.render();
  },

  offline() {
    $("runDot").className = "dot error";
    $("runText").textContent = "Server not reachable";
  },

  async runNow() {
    const result = await api.post("/api/run", {});
    toast(result.ok ? "Checking all portals. New leads appear when it finishes." : "A check is already running.");
    app.poll();
  },

  toggle() {
    $("activity").hidden = !$("activity").hidden;
    if (!$("activity").hidden) this.render();
  },

  close() {
    $("activity").hidden = true;
  },

  render() {
    const status = this.status;
    if (!status) return;
    const runs = status.runs.map((run) => `
      <div class="run"><span class="dot ${run.status}"></span><div class="run-main">
        <div class="run-title">${run.status === "running" ? "Running" : `${run.new_count} new of ${run.total}`}
          <span>${when(run.started)} · ${run.trigger}</span></div>
        <div class="run-sources">${Object.entries(run.sources).map(([name, s]) => s.ok
          ? `${esc(SOURCE_LABELS[name] || name)} ${s.count}`
          : `<span class="fail" title="${esc(s.error)}">${esc(SOURCE_LABELS[name] || name)} failed</span>`).join(" · ")}
          ${run.error ? `<span class="fail">${esc(run.error)}</span>` : ""}</div>
      </div></div>`).join("");
    const hours = status.scheduler.interval_hours;
    $("activity").innerHTML = `<h3>Recent checks</h3>${runs || '<div class="note">No checks yet.</div>'}
      <div class="note">Checks every ${hours} hours while this computer is awake. A check missed during sleep runs on wake.</div>`;
  },
};

/** Floating display settings, saved in the browser. */
const tweaks = {
  bind(app) {
    $("tweaksToggle").addEventListener("click", () => { $("tweaksPanel").hidden = !$("tweaksPanel").hidden; this.render(app); });
    $("tweaksPanel").addEventListener("click", (e) => {
      const option = e.target.closest("[data-pref]");
      if (!option) return;
      app.prefs[option.dataset.pref] = option.dataset.value;
      app.applyPrefs();
      app.render();
      this.render(app);
    });
    drawer.bind(app);
  },

  render(app) {
    $("tweaksPanel").innerHTML = Object.entries(TWEAKS).map(([key, tweak]) => `
      <div class="tweak">${tweak.label}<div class="seg">${tweak.options.map(([value, label]) =>
        `<button data-pref="${key}" data-value="${value}" class="${app.prefs[key] === value ? "on" : ""}">${label}</button>`).join("")}</div></div>`
    ).join("");
  },
};

/* Time formatting: the server stores UTC as "YYYY-MM-DD HH:MM:SS". */

function utc(text) {
  return new Date(`${text.replace(" ", "T")}Z`);
}

function ago(text, short = false) {
  const minutes = Math.max(0, Math.round((Date.now() - utc(text)) / 60000));
  if (minutes < 1) return short ? "just started" : "just now";
  if (minutes < 60) return `${minutes} min${short ? "" : " ago"}`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h${short ? "" : " ago"}`;
  return `${Math.round(hours / 24)} days ago`;
}

function clock(text) {
  const d = utc(text);
  if (d <= new Date()) return "soon";
  const sameDay = d.toDateString() === new Date().toDateString();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return sameDay ? time : `${d.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

function when(text) {
  return utc(text).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

const app = new Dashboard();
app.start();
