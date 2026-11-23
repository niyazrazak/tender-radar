"use strict";

const PAGE_SIZE = 120;
const POLL_MS = 10000;
const TABS = [
  ["active", "All active"], ["new", "Inbox"], ["shortlisted", "Shortlisted"],
  ["bidding", "Bidding"], ["dismissed", "Dismissed"],
];
// 20px line icons for the sidebar views.
const TAB_ICONS = {
  active: '<path d="M4 6h12M4 10h12M4 14h8" stroke-linecap="round"/>',
  new: '<path d="M3.5 11 6 4.5h8l2.5 6.5v4.5h-13zM3.5 11h4l1 2h3l1-2h4" stroke-linejoin="round"/>',
  shortlisted: '<path d="m10 3.5 2 4.2 4.5.6-3.3 3.1.8 4.5L10 13.7l-4 2.2.8-4.5-3.3-3.1 4.5-.6z" stroke-linejoin="round"/>',
  bidding: '<path d="M5 3.5h7l3 3v10H5zM8 10h4M8 13h4" stroke-linejoin="round" stroke-linecap="round"/>',
  dismissed: '<path d="M4 6h12M8 6V4h4v2M6 6l.7 10h6.6L14 6" stroke-linejoin="round" stroke-linecap="round"/>',
};
// Portal status of a tender. "opened" is Oman: bids opened, not yet awarded.
const STATUS_LABELS = { open: "Open", future: "Upcoming", opened: "Bids opened", awarded: "Awarded" };
const STATE_LABELS = { new: "", shortlisted: "Shortlisted", bidding: "Bidding", dismissed: "Dismissed" };
const SOURCE_LABELS = {
  monaqasat: "Monaqasat", mwani: "Mwani Qatar", qfa: "Qatar Football Association", etimad: "Etimad",
  sidra: "Sidra Medicine", woqod: "WOQOD", qafco: "QAFCO",
  oman_tender_board: "Oman Tender Board", kuwait_capt: "Kuwait CAPT", bahrain_tender_board: "Bahrain Tender Board",
};
const TWEAKS = {
  density: { label: "Density", options: [["relaxed", "Relaxed"], ["compact", "Compact"]] },
  keywords: { label: "Keywords", options: [["hide", "Hide"], ["show", "Show"]] },
  lang: { label: "Titles", options: [["en", "English"], ["orig", "Original"]] },
  theme: { label: "Theme", options: [["light", "Light"], ["dark", "Dark"]] },
};

const $ = (id) => document.getElementById(id);

/** Talks to the local server. */
const api = {
  async get(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error((await response.json()).error || response.statusText);
    return response.json();
  },
  async post(path, body) {
    const response = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    return { ok: response.ok, status: response.status, data: await response.json() };
  },
};

/** Holds the leads and the filters, and turns them into the visible list. */
class Dashboard {
  constructor() {
    this.leads = [];
    this.filters = {
      tab: "active", q: "", country: "", status: "", fee: "", bond: "", size: "", sort: "match", quick: "", scopeAll: false,
    };
    this.shown = PAGE_SIZE;
    this.selected = -1;
    this.visible = [];
    this.lastRunId = null;
    const theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    this.prefs = { density: "relaxed", keywords: "hide", lang: "en", theme, ...JSON.parse(localStorage.prefs || "{}") };
  }

  async start() {
    this.applyPrefs();
    this.bindControls();
    this.bindKeys();
    await Promise.all([this.loadLeads(), this.poll()]);
    setInterval(() => this.poll(), POLL_MS);
  }

  async loadLeads() {
    const scope = this.filters.scopeAll ? "all" : "relevant";
    try {
      const data = await api.get(`/api/leads?scope=${scope}`);
      this.leads = data.leads;
      this.aiEnabled = data.ai_enabled;
      this.smallCompany = data.small_company || { enabled: false, max_upfront_usd: 2000 };
      // Small company mode in config.json starts the list on tenders a small company can afford, once.
      if (!this.sizeApplied && this.smallCompany.enabled) { this.filters.size = "small"; $("size").value = "small"; }
      this.freelancer = data.freelancer || { enabled: false, award_days: 30 };
      // Freelancer mode starts on fresh awards: the winners may need help to deliver.
      if (!this.sizeApplied && this.freelancer.enabled) { this.filters.size = "awarded"; $("size").value = "awarded"; }
      this.sizeApplied = true;
      $("size").querySelector('[value="awarded"]').textContent =
        `Awarded in the last ${this.freelancer.award_days} days: pitch the winner`;
      $("size").querySelector('[value="cheap"]').textContent =
        `Up-front cost up to $${this.smallCompany.max_upfront_usd.toLocaleString("en-US")}`;
      this.loadFailed = false;
      // Start on the focus country once; after that the user's choice stands.
      if (!this.focusApplied) this.filters.country = (data.focus_countries || [])[0] || "";
      this.focusApplied = true;
    } catch (error) {
      this.loadFailed = true;  // poll() retries
      toast(`Could not load leads: ${error.message}`);
    }
    this.fillCountries();
    this.fillStatuses();
    this.render();
  }

  async poll() {
    try {
      const status = await api.get("/api/status");
      $("company").textContent = status.company;
      runPanel.update(status);
      const last = status.runs.find((run) => run.status !== "running");
      if (this.lastRunId !== null && last && last.id !== this.lastRunId) {
        toast(last.new_count ? `Check finished · ${last.new_count} new tenders` : "Check finished · nothing new");
        await this.loadLeads();
      } else if (this.loadFailed) {
        await this.loadLeads();
      }
      this.lastRunId = last ? last.id : 0;
    } catch {
      runPanel.offline();
    }
  }

  /** Saves notes, owner or bid deadline. Returns true when the server took it. */
  async saveTeamFields(lead, fields) {
    const result = await api.post("/api/lead-update", { key: lead.key, ...fields });
    if (!result.ok) { toast(`Could not save: ${result.data.error}`); return false; }
    Object.assign(lead, fields);
    this.render();
    return true;
  }

  async setState(lead, state) {
    const previous = lead.lead_status;
    lead.lead_status = lead.lead_status === state ? "new" : state;
    this.render();
    drawer.refresh();
    const result = await api.post("/api/lead-status", { key: lead.key, status: lead.lead_status });
    if (!result.ok) {
      lead.lead_status = previous;
      this.render();
      toast(`Could not save: ${result.data.error}`);
    }
  }

  /* Filtering */

  render() {
    const today = todayISO();
    const base = this.leads.filter((lead) => this.matchesSearch(lead) && this.matchesCountry(lead) && this.matchesStatus(lead)
      && this.matchesFee(lead) && this.matchesBond(lead) && this.matchesSize(lead));
    renderSummary(base, today, this.filters.quick);
    renderTabs(base, this.filters.tab);
    this.visible = sortLeads(base.filter((l) => this.matchesTab(l) && this.matchesQuick(l, today)), this.filters.sort);
    this.selected = Math.min(this.selected, this.visible.length - 1);
    renderList(this.visible.slice(0, this.shown), this.selected, this.prefs.lang, today);
    renderQuick(this.filters.quick, this.visible.length);
    const f = this.filters;
    $("clearFilters").hidden = !(f.country || f.status || f.fee || f.bond || f.size || f.q || f.quick);
    renderEmpty(this.visible.length === 0, this.leads.length === 0);
    const rest = this.visible.length - this.shown;
    $("more").hidden = rest <= 0;
    $("more").textContent = `Show ${Math.min(rest, PAGE_SIZE)} more of ${rest}`;
  }

  matchesSearch(lead) {
    const q = this.filters.q.trim().toLowerCase();
    if (!q) return true;
    const text = [lead.title, lead.title_en, lead.buyer, lead.buyer_en, lead.ref_no, lead.matched,
      lead.category_en, lead.activities_en, lead.brief_en, lead.ai_reason, lead.notes, lead.owner].join(" ").toLowerCase();
    return q.split(/\s+/).every((word) => text.includes(word));
  }

  matchesCountry(lead) {
    return !this.filters.country || lead.country === this.filters.country;
  }

  matchesStatus(lead) {
    return !this.filters.status || lead.status === this.filters.status;
  }

  matchesFee(lead) {
    return !this.filters.fee || feeKind(lead) === this.filters.fee;
  }

  matchesBond(lead) {
    const filter = this.filters.bond;
    if (!filter) return true;
    if (filter in BOND_LIMITS_USD) {
      const usd = bondUSD(lead);
      return usd !== null && usd <= BOND_LIMITS_USD[filter] && (filter !== "over100k" || usd > 100000);
    }
    return bondKind(lead) === filter;
  }

  matchesSize(lead) {
    const small = lead.small || {};
    const tests = {
      small: () => small.fits,
      sme: () => small.sme_reserved,
      smallvalue: () => Boolean(small.small_value),
      cheap: () => small.upfront_usd !== null && small.upfront_usd <= this.smallCompany.max_upfront_usd,
      awarded: () => isFreshAward(lead, this.freelancer.award_days),
      freelancer: () => small.freelancer_open && (lead.status === "open" || lead.status === "future"),
    };
    return !this.filters.size || tests[this.filters.size]();
  }

  matchesTab(lead) {
    if (this.filters.tab === "active") return lead.lead_status !== "dismissed";
    return lead.lead_status === this.filters.tab;
  }

  matchesQuick(lead, today) {
    const quick = this.filters.quick;
    if (quick === "fresh") return lead.first_seen >= daysAgoISO(7);
    if (quick === "closing") return isClosingSoon(lead, today);
    if (quick === "open") return lead.status === "open" || lead.status === "future";
    return true;
  }

  fillCountries() {
    const select = $("country");
    const countries = [...new Set(this.leads.map((l) => l.country))].sort();
    select.innerHTML = `<option value="">All countries</option>` +
      countries.map((c) => `<option ${c === this.filters.country ? "selected" : ""}>${esc(c)}</option>`).join("");
  }

  /** Statuses present in the data, with counts, in the order a tender moves through them. */
  fillStatuses() {
    const counts = {};
    for (const lead of this.leads) counts[lead.status] = (counts[lead.status] || 0) + 1;
    const order = [...Object.keys(STATUS_LABELS), ...Object.keys(counts).filter((s) => !(s in STATUS_LABELS))];
    $("status").innerHTML = `<option value="">Any status</option>` + order.filter((s) => counts[s]).map((s) =>
      `<option value="${esc(s)}" ${s === this.filters.status ? "selected" : ""}>${esc(STATUS_LABELS[s] || s)} (${counts[s]})</option>`
    ).join("");
  }

  /* Controls */

  bindControls() {
    const refilter = () => { this.shown = PAGE_SIZE; this.selected = -1; this.render(); };
    $("q").addEventListener("input", (e) => { this.filters.q = e.target.value; refilter(); });
    $("country").addEventListener("change", (e) => { this.filters.country = e.target.value; refilter(); });
    $("status").addEventListener("change", (e) => { this.filters.status = e.target.value; refilter(); });
    $("fee").addEventListener("change", (e) => { this.filters.fee = e.target.value; refilter(); });
    $("bond").addEventListener("change", (e) => { this.filters.bond = e.target.value; refilter(); });
    $("size").addEventListener("change", (e) => { this.filters.size = e.target.value; refilter(); });
    $("sort").addEventListener("change", (e) => { this.filters.sort = e.target.value; refilter(); });
    $("scopeAll").addEventListener("change", (e) => { this.filters.scopeAll = e.target.checked; this.loadLeads(); });
    $("tabs").addEventListener("click", (e) => {
      const tab = e.target.closest("[data-tab]");
      if (tab) { this.filters.tab = tab.dataset.tab; refilter(); }
    });
    $("summary").addEventListener("click", (e) => {
      const metric = e.target.closest("[data-quick]");
      if (!metric) return;
      const quick = metric.dataset.quick;
      if (quick === "shortlisted") { this.filters.tab = "shortlisted"; this.filters.quick = ""; }
      else this.filters.quick = this.filters.quick === quick ? "" : quick;
      refilter();
    });
    $("quick").addEventListener("click", (e) => { if (e.target.closest("button")) { this.filters.quick = ""; refilter(); } });
    $("clearFilters").addEventListener("click", () => {
      Object.assign(this.filters, { country: "", status: "", fee: "", bond: "", size: "", q: "", quick: "" });
      for (const id of ["country", "status", "fee", "bond", "size", "q"]) $(id).value = "";
      refilter();
    });
    $("list").addEventListener("click", (e) => {
      const row = e.target.closest("[data-i]");
      if (row) this.open(Number(row.dataset.i));
    });
    $("more").addEventListener("click", () => { this.shown += PAGE_SIZE; this.render(); });
    $("runNow").addEventListener("click", () => runPanel.runNow());
    $("marketBtn").addEventListener("click", () => market.toggle());
    $("companyBtn").addEventListener("click", () => company.toggle());
    $("outreachBtn").addEventListener("click", () => outreach.toggle());
    $("company").addEventListener("click", () => company.toggle());
    $("runState").addEventListener("click", (e) => { e.stopPropagation(); runPanel.toggle(); });
    document.addEventListener("click", (e) => { if (!e.target.closest("#activity")) runPanel.close(); });
    tweaks.bind(this);
  }

  bindKeys() {
    document.addEventListener("keydown", (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.target.matches("input, select, textarea")) {
        if (e.key === "Escape") e.target.blur();
        return;
      }
      const lead = this.visible[this.selected];
      const actions = {
        j: () => this.move(1), ArrowDown: () => this.move(1),
        k: () => this.move(-1), ArrowUp: () => this.move(-1),
        Enter: () => this.selected >= 0 && this.open(this.selected),
        o: () => lead && window.open(lead.url, "_blank"),
        Escape: () => (outreach.isOpen() ? outreach.close() : company.isOpen() ? company.close()
          : market.isOpen() ? market.close() : drawer.close()),
        m: () => market.toggle(),
        c: () => company.toggle(),
        e: () => outreach.toggle(),
        "/": () => $("q").focus(),
        s: () => lead && this.setState(lead, "shortlisted"),
        b: () => lead && this.setState(lead, "bidding"),
        d: () => lead && this.setState(lead, "dismissed"),
        u: () => lead && this.setState(lead, "new"),
      };
      if (actions[e.key]) { e.preventDefault(); actions[e.key](); }
    });
  }

  move(step) {
    if (!this.visible.length) return;
    this.selected = Math.max(0, Math.min(this.visible.length - 1, this.selected + step));
    if (this.selected >= this.shown) this.shown += PAGE_SIZE;
    this.render();
    document.querySelector(".row.sel")?.scrollIntoView({ block: "nearest" });
    if (drawer.isOpen()) drawer.show(this.visible[this.selected]);
  }

  open(index) {
    this.selected = index;
    this.render();
    drawer.show(this.visible[index]);
  }

  applyPrefs() {
    document.documentElement.dataset.density = this.prefs.density;
    document.documentElement.dataset.keywords = this.prefs.keywords;
    document.documentElement.dataset.theme = this.prefs.theme;
    localStorage.prefs = JSON.stringify(this.prefs);
  }
}

/* Rendering */

function renderSummary(leads, today, quick) {
  const live = leads.filter((l) => l.lead_status !== "dismissed");
  const closing = live.filter((l) => isClosingSoon(l, today)).length;
  const metrics = [
    ["open", live.filter((l) => l.status === "open" || l.status === "future").length, "Open leads"],
    ["fresh", live.filter((l) => l.first_seen >= daysAgoISO(7)).length, "New this week"],
    ["closing", closing, "Closing within 7 days", closing ? "urgent" : ""],
    ["shortlisted", live.filter((l) => l.lead_status === "shortlisted").length, "Shortlisted"],
  ];
  $("summary").innerHTML = metrics.map(([key, n, label, cls = ""]) =>
    `<button class="metric ${cls} ${quick === key ? "on" : ""}" data-quick="${key}"><b>${n}</b><span>${label}</span></button>`
  ).join("");
}

function renderTabs(leads, current) {
  $("tabs").innerHTML = TABS.map(([key, label]) => {
    const n = leads.filter((l) => (key === "active" ? l.lead_status !== "dismissed" : l.lead_status === key)).length;
    const icon = `<svg viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6">${TAB_ICONS[key]}</svg>`;
    return `<button class="tab ${key === current ? "on" : ""}" data-tab="${key}">${icon}<span>${label}</span><span class="n">${n || ""}</span></button>`;
  }).join("");
}

function renderList(leads, selected, lang, today) {
  $("list").innerHTML = leads.map((lead, i) => {
    const title = lang === "orig" ? lead.title : lead.title_en || lead.title;
    const isNew = lead.first_seen >= daysAgoISO(1);
    const status = lead.status !== "open" ? `<span class="badge state">${esc(STATUS_LABELS[lead.status] || lead.status)}</span>` : "";
    return `<li class="row ${i === selected ? "sel" : ""}" data-i="${i}">
      <div class="lane-score">${matchBadge(lead)}</div>
      <div class="lane-main">
        <div class="title" dir="auto">${status}${smallBadges(lead)}${esc(title)}</div>
        <div class="meta">${STATE_LABELS[lead.lead_status] ? `<span class="pill ${lead.lead_status}">${STATE_LABELS[lead.lead_status]}</span>` : ""}
          <span dir="auto">${esc(lead.buyer_en || lead.buyer || "Unknown buyer")}</span>
          <span class="sep"></span><span>${esc(lead.country)}</span>
          ${lead.ref_no ? `<span class="sep"></span><span class="ref">${esc(lead.ref_no)}</span>` : ""}
          ${lead.owner ? `<span class="sep"></span><span title="Owner">Owner: ${esc(lead.owner)}</span>` : ""}
          ${isNew ? '<span class="sep"></span><span class="new-label">New today</span>' : ""}</div>
        ${lead.ai_reason ? `<div class="reason">${esc(lead.ai_reason)}</div>` : ""}
        ${chips(lead.matched)}
      </div>
      <div class="lane-money">${moneyLines(lead)}</div>
      <div class="lane-date">${deadline(lead, today)}</div>
    </li>`;
  }).join("");
}

/** One number per row: Claude's fit when it has rated the lead, else the keyword score. */
function matchBadge(lead) {
  if (lead.ai_fit !== null && lead.ai_fit !== undefined) {
    const level = lead.ai_fit >= 7 ? "high" : lead.ai_fit >= 4 ? "mid" : "low";
    return `<span class="match ${level}" title="AI fit ${lead.ai_fit}/10 · keyword score ${lead.score}">
      <b>${lead.ai_fit}</b><small>fit</small></span>`;
  }
  return `<span class="match kw ${lead.score >= 6 ? "high" : ""}" title="Keyword score">
    <b>${lead.score}</b><small>score</small></span>`;
}

function moneyLines(lead) {
  const fee = feeKind(lead);
  const feeText = fee === "unlisted" ? '<span class="na">not listed</span>'
    : fee === "free" ? '<span class="free">Free</span>' : esc(fmtFee(lead));
  const bond = bondKind(lead) === "unlisted" ? '<span class="na">not listed</span>' : esc(fmtBond(lead).replace(" of bid value", " of bid"));
  return `<div><span class="k">Fee</span>${feeText}</div><div><span class="k">Bond</span>${bond}</div>`;
}

/** Days left leads, because that is what decides whether to act today. */
function deadline(lead, today) {
  // For an awarded tender the portal's published date is the award date; its closing date no longer matters.
  if (lead.status === "awarded") {
    return `<div class="when past">Awarded</div><div class="d">${lead.published ? fmtDate(lead.published) : ""}</div>`;
  }
  if (!lead.closing) return '<div class="when na">No closing date</div>';
  const days = daysLeft(lead.closing, today);
  const cls = days < 0 ? "past" : days <= 3 ? "urgent" : days <= 7 ? "soon" : "";
  const text = days < 0 ? "Closed" : days === 0 ? "Today" : `${days} day${days === 1 ? "" : "s"}`;
  return `<div class="when ${cls}">${text}</div><div class="d">${fmtDate(lead.closing)}</div>`;
}

/** AI fit 0-10, shown only once Claude has rated the lead. */
function fitBadge(lead) {
  if (lead.ai_fit === null || lead.ai_fit === undefined) return "";
  const level = lead.ai_fit >= 7 ? "high" : lead.ai_fit >= 4 ? "mid" : "low";
  return `<span class="fit ${level}" title="AI fit ${lead.ai_fit}/10: ${esc(lead.ai_reason)}">${lead.ai_fit}</span>`;
}

function renderQuick(quick, count) {
  const labels = { fresh: "First seen in the last 7 days", closing: "Closing within 7 days", open: "Open or upcoming" };
  const chip = labels[quick] ? `<span class="filter-chip">${labels[quick]}<button aria-label="Clear">×</button></span>` : "";
  $("quick").innerHTML = `<b>${count.toLocaleString("en-US")}</b> ${count === 1 ? "lead" : "leads"} ${chip}`;
}

function renderEmpty(empty, noData) {
  $("empty").hidden = !empty;
  $("empty").innerHTML = noData
    ? "<b>No leads yet</b>Press “Check now” to collect tenders from the portals. The first check takes about 10 minutes."
    : "<b>Nothing matches</b>Try another view, clear the filters, or include non-matching tenders.";
}

function chips(matched) {
  if (!matched) return "";
  const [hits, excluded = ""] = matched.split(" | excluded: ");
  const words = hits.split(", ").filter(Boolean).slice(0, 6).map((w) => `<span class="chip" dir="auto">${esc(w)}</span>`);
  const negative = excluded.split(", ").filter(Boolean).map((w) => `<span class="chip neg" dir="auto">− ${esc(w)}</span>`);
  return `<div class="chips">${words.join("")}${negative.join("")}</div>`;
}

function sortLeads(leads, sort) {
  const closing = (l) => l.closing || "9999";
  const orders = {
    match: (a, b) => b.score - a.score || closing(a).localeCompare(closing(b)),
    fit: (a, b) => (b.ai_fit ?? -1) - (a.ai_fit ?? -1) || b.score - a.score,
    closing: (a, b) => closing(a).localeCompare(closing(b)) || b.score - a.score,
    fee: (a, b) => feeUSD(a) - feeUSD(b) || b.score - a.score,
    upfront: (a, b) => upfrontUSD(a) - upfrontUSD(b) || b.score - a.score,
    newest: (a, b) => b.first_seen.localeCompare(a.first_seen) || b.score - a.score,
  };
  return [...leads].sort(orders[sort]);
}

/* Money. Fee and bond: "" means the portal did not list one; 0 means none is charged. */

function moneyAmount(text) {
  if (text === null || text === undefined || String(text).trim() === "") return null;
  const amount = parseFloat(String(text).replace(/,/g, ""));
  return isNaN(amount) ? null : amount;
}

// Gulf currencies are pegged to the US dollar (Kuwait's to a basket, so its rate is approximate):
// fixed rates compare amounts across countries.
const USD_PER = { QAR: 1 / 3.64, SAR: 1 / 3.75, OMR: 1 / 0.3845, AED: 1 / 3.6725, KWD: 3.25, BHD: 1 / 0.376 };

// "Up to" limits for the bond filter; a bond of 0 counts as within every limit.
const BOND_LIMITS_USD = { upto5k: 5000, upto25k: 25000, upto100k: 100000, over100k: Infinity };

function toUSD(amount, currency) {
  return amount * (USD_PER[currency] ?? 1);
}

/** Document fee + bid bond in dollars; unknown (bond as % or not listed) sorts last. */
function upfrontUSD(lead) {
  const usd = lead.small?.upfront_usd;
  return usd === null || usd === undefined ? Infinity : usd;
}

function fmtUSD(amount) {
  return `$${Math.round(amount).toLocaleString("en-US")}`;
}

/** Awarded within `days` days, with a winner to pitch. For awarded tenders `published` is the award date. */
function isFreshAward(lead, days) {
  return lead.status === "awarded" && (lead.extra?.winners || []).length > 0 && (lead.published || "") >= daysAgoISO(days);
}

function smallBadges(lead) {
  const small = lead.small || {};
  const badges = [];
  if (small.sme_reserved) badges.push('<span class="badge sme" title="Reserved for small and medium enterprises">SME only</span>');
  if (small.freelancer_open) badges.push('<span class="badge sme" title="Open to licensed freelancers">Freelancers</span>');
  if (small.small_value) badges.push(`<span class="badge small" title="${esc(small.small_value)}">Small value</span>`);
  return badges.join("");
}

function feeUSD(lead) {
  const amount = moneyAmount(lead.doc_fee);
  return amount === null ? Infinity : toUSD(amount, lead.currency);  // not listed sorts last
}

function fmtMoney(amount, currency) {
  return `${amount.toLocaleString("en-US", { maximumFractionDigits: 3 })} ${currency || ""}`.trim();
}

/* Bid bond: an amount, or (Oman) a percent of the bid such as "2%". */

function bondKind(lead) {
  const text = String(lead.bond ?? "").trim();
  if (text.endsWith("%")) return "percent";
  const amount = moneyAmount(text);
  return amount === null ? "unlisted" : amount === 0 ? "none" : "amount";
}

function bondUSD(lead) {
  const kind = bondKind(lead);
  if (kind === "none") return 0;
  return kind === "amount" ? toUSD(moneyAmount(lead.bond), lead.currency) : null;
}

function fmtBond(lead) {
  const kind = bondKind(lead);
  if (kind === "percent") return `${lead.bond.trim()} of bid value`;
  if (kind === "none") return "None required";
  if (kind === "amount") return fmtMoney(moneyAmount(lead.bond), lead.currency);
  return "";
}

function feeKind(lead) {
  const amount = moneyAmount(lead.doc_fee);
  return amount === null ? "unlisted" : amount === 0 ? "free" : "paid";
}

function fmtFee(lead) {
  const amount = moneyAmount(lead.doc_fee);
  if (amount === null) return "";
  if (amount === 0) return "Free";
  return fmtMoney(amount, lead.currency);
}

/* Helpers */

function isClosingSoon(lead, today) {
  if (lead.status === "awarded") return false;
  const left = daysLeft(lead.closing, today);
  return left !== null && left >= 0 && left <= 7;
}

function daysLeft(closing, today) {
  if (!closing) return null;
  return Math.round((Date.parse(closing) - Date.parse(today)) / 86400000);
}

function todayISO() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function daysAgoISO(days) {
  return new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
}

function fmtDate(iso) {
  const d = new Date(`${iso}T00:00:00`);
  return isNaN(d) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** English first, the original below it when they differ: company names are read in both. */
function bilingual(english, original) {
  if (!english || english === original) return `<span dir="auto">${esc(original)}</span>`;
  return `<span>${esc(english)}</span><div class="orig" dir="auto">${esc(original)}</div>`;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

let toastTimer;
function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("toast").classList.remove("show"), 4000);
}
