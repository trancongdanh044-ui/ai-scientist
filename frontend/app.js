/* AI Scientist — giao diện web. Không phụ thuộc thư viện ngoài. */
"use strict";

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- icons
const ICONS = {
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  refresh: '<path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 21v-5h5"/><path d="M3 12A9 9 0 0 1 18.5 5.8L21 8"/><path d="M21 3v5h-5"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>',
  zip: '<path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><path d="M10 12h4"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14L21 3"/>',
  play: '<path d="M5 3l14 9-14 9z"/>',
  flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3"/>',
};
const icon = (n) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n] || ""}</svg>`;

// ---------------------------------------------------------------- hằng số
const PHASES = [
  { title: "Khảo sát", steps: [["literature", "Khảo sát tài liệu"], ["hypothesis", "Sinh giả thuyết"]] },
  { title: "Viết bài", steps: [
    ["writing_abstract", "Abstract"], ["writing_intro", "Introduction"], ["writing_related", "Related Work"],
    ["writing_method", "Methodology"], ["writing_expdesign", "Experiments"], ["writing_conclusion", "Conclusion"]] },
  { title: "Kiểm tra & dựng", steps: [
    ["figures", "Vẽ hình từ dữ liệu thật"], ["tables", "Dựng bảng"], ["sanitize", "Công thức, trích dẫn, số liệu"],
    ["render", "Mã LaTeX (IEEEtran)"], ["compile", "Xuất PDF hai cột"]] },
  { title: "Hoàn thiện", steps: [["review", "Tự bình duyệt"]] },
];
const SECTION_TITLES = {
  abstract: "Abstract", introduction: "1. Introduction", preliminaries: "2. Preliminaries", methodology: "3. Method",
  experiments_intro: "4. Experiments", experiments_setup: "4.1 Experimental Settings",
  exp_comparison: "4.2 Performance Comparison (RQ1)", exp_ablation: "4.3 Ablation Study (RQ2)",
  exp_sensitivity: "4.4 Sensitivity Analysis (RQ3)", related_work: "5. Related Work", conclusion: "6. Conclusion and Future Work",
};
const EXAMPLES = [
  "Parameter-Efficient Fine-Tuning for Vietnamese NLP",
  "Retrieval-Augmented Generation for Legal Question Answering",
  "Lightweight Object Detection on Edge Devices",
  "Graph Neural Networks for Fake News Detection",
  "Federated Learning for Medical Image Classification",
];
const STATUS_LABEL = { pending: "Chờ", running: "Đang chạy", done: "Hoàn tất", completed: "Hoàn tất", error: "Lỗi", failed: "Lỗi" };

const state = { runId: null, es: null, poll: null, timer: null, startedAt: 0, live: {}, detail: null, files: [], tab: null };

// ---------------------------------------------------------------- tiện ích
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
const pad = (n) => String(n).padStart(2, "0");
const fmtElapsed = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${pad(Math.floor(s / 60))}:${pad(s % 60)}`; };
const fmtSize = (b) => (b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");

function timeAgo(iso) {
  if (!iso) return "";
  const d = new Date(iso); const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "vừa xong";
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} ngày trước`;
  return d.toLocaleDateString("vi-VN");
}

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind; el.textContent = msg;
  $("toasts").appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; setTimeout(() => el.remove(), 300); }, kind === "error" ? 6000 : 3500);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = ""; try { detail = JSON.stringify((await res.json()).detail); } catch (_) { /* bỏ qua */ }
    throw new Error(detail || `Lỗi ${res.status}`);
  }
  return res;
}

// Định dạng văn bản bài báo: đoạn, danh sách, in đậm, công thức hiển thị
function formatProse(raw) {
  const parts = []; let last = 0;
  const re = /\\begin\{(equation|align|gather|multline)\*?\}([\s\S]*?)\\end\{\1\*?\}/g; let m;
  const text = String(raw || "");
  while ((m = re.exec(text))) { parts.push({ t: text.slice(last, m.index) }); parts.push({ eq: m[2].trim() }); last = re.lastIndex; }
  parts.push({ t: text.slice(last) });
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\\cite[a-z]*\{[^}]*\}/g, '<sup>[ref]</sup>')
    .replace(/\\paragraph\{([^}]*)\}/g, "<strong>$1</strong>")
    .replace(/\\(?:textbf|emph|textit)\{([^{}]*)\}/g, "<strong>$1</strong>")
    .replace(/\$([^$\n]+)\$/g, "<code>$1</code>")
    .replace(/~/g, "&nbsp;");
  let html = "";
  for (const p of parts) {
    if (p.eq !== undefined) { html += `<div class="eq">${esc(p.eq.replace(/\\label\{[^}]*\}/g, ""))}</div>`; continue; }
    let para = [], list = null;
    const flushPara = () => { if (para.length) { html += `<p>${inline(para.join(" "))}</p>`; para = []; } };
    const flushList = () => { if (list) { html += `<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`; list = null; } };
    for (const line of p.t.split("\n")) {
      const li = line.match(/^\s*(?:([-*•])|(\d+)[.)])\s+(.*\S)\s*$/);
      if (li) { flushPara(); const tag = li[2] ? "ol" : "ul"; if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; } list.items.push(li[3]); }
      else if (!line.trim()) { flushPara(); flushList(); }
      else { flushList(); para.push(line.trim()); flushPara(); }
    }
    flushPara(); flushList();
  }
  return html || '<p class="muted">Chưa có nội dung.</p>';
}

function tableHtml(rows, cols) {
  if (!rows?.length) return "";
  return `<div class="table-wrap"><table class="data"><thead><tr>${cols.map((c) => `<th>${esc(c[1])}</th>`).join("")}</tr></thead><tbody>${
    rows.map((r) => `<tr>${cols.map((c) => `<td>${esc(r[c[0]] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

// ---------------------------------------------------------------- giao diện chung
function initTheme() {
  const btn = $("themeBtn");
  const paint = () => { btn.innerHTML = icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon"); };
  btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next; localStorage.setItem("theme", next); paint();
  });
  paint();
  $("refreshHistory").innerHTML = icon("refresh");
}

async function initHealth() {
  const pill = $("healthPill");
  try {
    const h = await (await api("/api/health")).json();
    pill.className = "pill pill-ok";
    $("healthText").textContent = h.llm_model || "Sẵn sàng";
    pill.title = `Máy chủ hoạt động · ${h.llm_base_url || ""}`;
    const sel = $("model");
    if (h.llm_model && ![...sel.options].some((o) => o.value === h.llm_model)) sel.add(new Option(h.llm_model, h.llm_model), 0);
    if (h.llm_model) sel.value = localStorage.getItem("model") || h.llm_model;
  } catch (_) {
    pill.className = "pill pill-bad"; $("healthText").textContent = "Máy chủ không phản hồi";
  }
}

function initForm() {
  const topic = $("topic");
  const saved = JSON.parse(localStorage.getItem("form") || "{}");
  if (saved.topic) topic.value = saved.topic;
  if (saved.numPapers) $("numPapers").value = saved.numPapers;
  if (saved.maxHyp) $("maxHyp").value = saved.maxHyp;
  const count = () => { $("topicCount").textContent = `${topic.value.length}/300`; };
  topic.addEventListener("input", count); count();

  $("examples").innerHTML = EXAMPLES.map((e) => `<button type="button" class="chip">${esc(e)}</button>`).join("");
  $("examples").addEventListener("click", (ev) => {
    const b = ev.target.closest(".chip"); if (!b) return; topic.value = b.textContent; count(); topic.focus();
  });

  document.querySelectorAll(".stepper").forEach((st) => {
    const input = $(st.dataset.for);
    st.addEventListener("click", (ev) => {
      const b = ev.target.closest(".step-btn"); if (!b) return;
      const v = (+input.value || 0) + +b.dataset.dir;
      input.value = Math.min(+input.max, Math.max(+input.min, v));
    });
  });
  $("startBtn").addEventListener("click", startRun);
  topic.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") startRun(); });
  $("refreshHistory").addEventListener("click", () => loadHistory(true));
}

function setBusy(busy) {
  const b = $("startBtn");
  b.disabled = busy;
  b.querySelector(".btn-icon").innerHTML = busy ? '<span class="spinner"></span>' : icon("play");
  b.querySelector(".btn-label").textContent = busy ? "Đang thực hiện…" : "Bắt đầu nghiên cứu";
}

// ---------------------------------------------------------------- tiến trình
function buildPhases() {
  $("phases").innerHTML = PHASES.map((p, i) => `
    <div class="phase" data-phase="${i}">
      <div class="phase-title"><span>${i + 1}. ${esc(p.title)}</span><span class="phase-count">0/${p.steps.length}</span></div>
      <ul class="steps">${p.steps.map(([k, label]) => `<li class="step" data-stage="${k}"><span class="step-ico">${icon("check")}</span>${esc(label)}</li>`).join("")}</ul>
    </div>`).join("");
}

function setStep(stage, st) {
  const el = document.querySelector(`.step[data-stage="${stage}"]`); if (!el) return;
  el.classList.remove("active", "done"); if (st) el.classList.add(st);
  document.querySelectorAll(".phase").forEach((ph) => {
    const total = ph.querySelectorAll(".step").length, done = ph.querySelectorAll(".step.done").length;
    ph.querySelector(".phase-count").textContent = `${done}/${total}`;
  });
}

function setProgress(p, msg) {
  p = Math.max(0, Math.min(100, Math.round(p || 0)));
  $("progressFill").style.width = p + "%"; $("percentText").textContent = p + "%";
  $("progressBar").setAttribute("aria-valuenow", p);
  if (msg) $("stageMsg").textContent = msg;
}

function startTimer(from) {
  stopTimer(); state.startedAt = from || Date.now();
  const tick = () => { $("elapsedText").textContent = fmtElapsed(Date.now() - state.startedAt); };
  tick(); state.timer = setInterval(tick, 1000);
  $("progressBar").classList.add("running");
}
function stopTimer() { clearInterval(state.timer); state.timer = null; $("progressBar").classList.remove("running"); }

function showProgress(topic, d) {
  $("progressPanel").hidden = false; $("errorPanel").hidden = true; $("resultsPanel").hidden = true;
  $("runTopic").textContent = topic || ""; buildPhases(); setProgress(d?.progress || 0, d?.stage || "Đang khởi tạo…");
}

// ---------------------------------------------------------------- chạy mới
async function startRun() {
  const topic = $("topic").value.trim();
  if (topic.length < 5) { toast("Chủ đề quá ngắn — hãy nhập ít nhất 5 ký tự.", "error"); $("topic").focus(); return; }
  const body = { topic, num_papers: +$("numPapers").value || 8, max_hypotheses: +$("maxHyp").value || 3, model: $("model").value };
  localStorage.setItem("form", JSON.stringify({ topic, numPapers: body.num_papers, maxHyp: body.max_hypotheses }));
  localStorage.setItem("model", body.model);
  setBusy(true); closeStream();
  try {
    const { run_id } = await (await api("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
    state.runId = run_id; state.live = {};
    showProgress(topic); startTimer(); subscribe(run_id);
    $("progressPanel").scrollIntoView({ behavior: "smooth", block: "start" });
    loadHistory();
  } catch (e) { showError(e.message); setBusy(false); }
}

function closeStream() { if (state.es) { state.es.close(); state.es = null; } clearInterval(state.poll); state.poll = null; }

function subscribe(runId) {
  closeStream();
  const es = new EventSource(`/api/runs/${runId}/stream`); state.es = es;
  es.onmessage = (ev) => { try { handleEvent(JSON.parse(ev.data)); } catch (e) { console.error(e); } };
  es.onerror = () => { es.close(); if (state.es === es) { state.es = null; pollStatus(runId); } };
}

// SSE đứt giữa chừng: chuyển sang hỏi trạng thái định kỳ
function pollStatus(runId) {
  clearInterval(state.poll);
  state.poll = setInterval(async () => {
    try {
      const s = await (await api(`/api/runs/${runId}/status`)).json();
      setProgress(s.progress, s.stage);
      if (["done", "completed"].includes(s.status)) { clearInterval(state.poll); finishRun(runId); }
      else if (["error", "failed"].includes(s.status)) { clearInterval(state.poll); failRun(s.error || "Tiến trình gặp lỗi."); }
    } catch (_) { /* thử lại ở lượt sau */ }
  }, 3000);
}

function handleEvent(e) {
  if (e.type === "stage") {
    setProgress(e.progress, e.message); setStep(e.stage, "active");
  } else if (e.type === "stage_done") {
    setStep(e.stage, "done");
    if (e.stage === "sanitize") state.live.sanitize = e.preview;
    if (e.stage === "compile") state.live.compileOk = e.compile_ok;
  } else if (e.type === "done") {
    closeStream(); finishRun(state.runId);
  } else if (e.type === "error") {
    closeStream(); failRun(e.error);
  }
}

async function finishRun(runId) {
  stopTimer(); setProgress(100, "Hoàn thành — bài báo đã sẵn sàng.");
  document.querySelectorAll(".step").forEach((el) => { el.classList.remove("active"); el.classList.add("done"); });
  setBusy(false); toast("Đã hoàn thành bài báo.", "success");
  await showRun(runId); loadHistory();
  $("resultsPanel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function failRun(msg) { stopTimer(); showError(msg); setBusy(false); loadHistory(); }

function showError(msg) {
  $("errorPanel").hidden = false; $("errorMsg").textContent = msg || "Lỗi không xác định";
  $("errorPanel").scrollIntoView({ behavior: "smooth", block: "center" });
}

// ---------------------------------------------------------------- kết quả
async function showRun(runId) {
  try {
    const [detail, filesRes] = await Promise.all([
      api(`/api/runs/${runId}`).then((r) => r.json()),
      api(`/api/runs/${runId}/files`).then((r) => r.json()).catch(() => ({ files: [] })),
    ]);
    state.runId = runId; state.detail = detail; state.files = filesRes.files || [];
    renderResults();
  } catch (e) { showError(e.message); }
}

const fileOf = (name) => state.files.find((f) => f.name === name);

function renderResults() {
  const d = state.detail, files = state.files;
  $("resultsPanel").hidden = false;
  $("resultsTitle").textContent = d.topic || "Bài báo";

  const engine = d.compile_engine === "latex" ? ["PDF · LaTeX", "tag-ok"] : d.compile_engine === "reportlab" ? ["PDF · bản dự phòng", "tag-warn"] : null;
  const status = STATUS_LABEL[d.status] || d.status;
  $("resultMeta").innerHTML = [
    `<span class="tag ${["done", "completed"].includes(d.status) ? "tag-ok" : d.status === "error" ? "tag-bad" : "tag-brand"}">${esc(status)}</span>`,
    engine ? `<span class="tag ${engine[1]}">${engine[0]}</span>` : "",
    d.literature?.papers?.length ? `<span class="tag">${d.literature.papers.length} tài liệu tham khảo</span>` : "",
    d.model ? `<span class="tag">${esc(d.model)}</span>` : "",
    d.created_at ? `<span class="tag">${esc(timeAgo(d.created_at))}</span>` : "",
  ].join("");

  const pdf = fileOf("paper.pdf"), zip = fileOf("paper_bundle.zip"), tex = fileOf("paper.tex");
  $("resultActions").innerHTML = [
    pdf ? `<a class="btn btn-primary" href="${pdf.url}" download="paper.pdf">${icon("download")}Tải PDF</a>` : "",
    zip ? `<a class="btn" href="${zip.url}" download title="Upload lên Overleaf để có bản IEEEtran chuẩn">${icon("zip")}Gói Overleaf</a>` : "",
    tex ? `<a class="btn" href="${tex.url}" download>${icon("file")}paper.tex</a>` : "",
  ].join("");

  const b = $("pdfBanner");
  if (d.compile_ok === true) {
    b.hidden = false; b.className = "banner ok";
    b.innerHTML = "<strong>PDF đã sẵn sàng</strong> — bố cục hai cột, công thức đã được kiểm tra biên dịch, trích dẫn và số liệu đã được đối chiếu." +
      (d.compile_engine === "reportlab" ? '<div class="sub">Máy chủ chưa có LaTeX nên đây là bản dự phòng. Tải “Gói Overleaf” để có bản IEEEtran chuẩn.</div>' : "");
  } else if (d.compile_ok === false) {
    b.hidden = false; b.className = "banner warn"; b.textContent = "Chưa tạo được PDF. Xem tab “Tệp” để tải mã nguồn LaTeX.";
  } else b.hidden = true;

  const refs = d.literature?.papers || [];
  const tabs = [];
  if (pdf) tabs.push({ id: "pdf", label: "PDF", render: renderPdfTab });
  tabs.push({ id: "paper", label: "Nội dung", render: renderPaperTab });
  tabs.push({ id: "refs", label: "Tham khảo", count: refs.length, render: renderRefsTab });
  tabs.push({ id: "hyp", label: "Giả thuyết", render: renderHypTab });
  if (d.review) tabs.push({ id: "review", label: "Bình duyệt", render: () => `<div class="prose">${copyBtn()}${formatProse(d.review)}</div>` });
  if (fileOf("TODO.md")) tabs.push({ id: "todo", label: "Việc cần làm", render: renderTodoTab });
  tabs.push({ id: "files", label: "Hình & tệp", count: files.length, render: renderFilesTab });

  $("resultsTabs").innerHTML = tabs.map((t) => `<button class="tab" role="tab" id="tab-${t.id}" data-id="${t.id}" aria-selected="false">${esc(t.label)}${t.count != null ? `<span class="count">${t.count}</span>` : ""}</button>`).join("");
  const select = async (id) => {
    state.tab = id;
    document.querySelectorAll(".tab").forEach((el) => el.setAttribute("aria-selected", el.dataset.id === id));
    const t = tabs.find((x) => x.id === id);
    $("resultsContent").innerHTML = '<div class="skeleton"></div>';
    $("resultsContent").innerHTML = await t.render();
    bindPanel();
  };
  $("resultsTabs").onclick = (ev) => { const b2 = ev.target.closest(".tab"); if (b2) select(b2.dataset.id); };
  select(tabs.some((t) => t.id === state.tab) ? state.tab : tabs[0].id);
}

const copyBtn = () => `<div class="copy-row"><button class="btn btn-sm" data-copy type="button">${icon("copy")}Sao chép</button></div>`;

function bindPanel() {
  const panel = $("resultsContent");
  panel.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    const txt = panel.querySelector(".prose, .paper")?.innerText || "";
    try { await navigator.clipboard.writeText(txt); toast("Đã sao chép vào clipboard.", "success"); } catch (_) { toast("Không thể sao chép.", "error"); }
  }));
  panel.querySelectorAll(".fig").forEach((f) => f.addEventListener("click", () => {
    $("lightboxImg").src = f.dataset.src; $("lightboxCap").textContent = f.dataset.name; $("lightbox").showModal();
  }));
}

function renderPdfTab() {
  const pdf = fileOf("paper.pdf");
  return `<div class="pdf-frame"><iframe src="${pdf.url}#view=FitH" title="Xem trước PDF"></iframe></div>
    <p class="hint" style="margin-top:10px">Không hiển thị? <a href="${pdf.url}" target="_blank" rel="noopener">Mở PDF trong tab mới</a>.</p>`;
}

function renderPaperTab() {
  const order = Object.keys(SECTION_TITLES);
  const secs = [...(state.detail.sections || [])].sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name));
  if (!secs.length) return '<div class="empty">Chưa có nội dung.</div>';
  return copyBtn() + `<article class="paper">${secs.map((s) =>
    `<section><h3>${esc(SECTION_TITLES[s.name] || s.name)}</h3>${formatProse(s.content)}</section>`).join("")}</article>`;
}

function renderRefsTab() {
  const lit = state.detail.literature;
  if (!lit?.papers?.length) return '<div class="empty">Chưa có dữ liệu tài liệu tham khảo.</div>';
  const kindLabel = { journal: "Tạp chí", conference: "Hội nghị", preprint: "Preprint" };
  const items = lit.papers.map((p, i) => {
    const year = (p.published || "").slice(0, 4);
    const authors = (p.authors || []).slice(0, 4).join(", ") + ((p.authors || []).length > 4 || p.more_authors ? " et al." : "");
    const link = p.doi ? `https://doi.org/${p.doi}` : safeUrl(p.url);
    return `<div class="ref"><div class="ref-num">[${i + 1}]</div><div>
      <div class="ref-title">${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">${esc(p.title)}</a>` : esc(p.title)}</div>
      <div class="ref-meta">${esc(authors)}${year ? ` · ${year}` : ""}${p.venue ? ` · ${esc(p.venue)}` : ""}</div>
      <div class="ref-tags">
        ${p.kind ? `<span class="tag ${p.kind === "preprint" ? "" : "tag-brand"}">${kindLabel[p.kind] || esc(p.kind)}</span>` : ""}
        ${p.doi ? `<span class="tag tag-ok" title="Bài có DOI trong chỉ mục học thuật">Có DOI</span>` : ""}
        ${p.citations ? `<span class="tag">${p.citations} trích dẫn</span>` : ""}
        ${p.source ? `<span class="tag">${esc(p.source)}</span>` : ""}
      </div></div></div>`;
  }).join("");
  return `<div class="refs">${items}</div>
    <div class="prose"><h4>Tóm tắt khảo sát</h4>${formatProse(lit.summaries)}<h4>Khoảng trống nghiên cứu</h4>${formatProse(lit.research_gap)}</div>`;
}

function renderHypTab() {
  const d = state.detail;
  return `<div class="prose"><h4>Giả thuyết</h4>${formatProse(d.hypotheses)}</div>
    <h4 class="muted small" style="text-transform:uppercase;letter-spacing:.08em;margin:18px 0 6px">Kế hoạch đánh giá</h4>
    ${tableHtml(d.eval_rows, [["hypothesis", "Giả thuyết"], ["baseline", "Baseline"], ["metric", "Độ đo"], ["dataset", "Dữ liệu"]]) || '<p class="muted">Chưa có.</p>'}
    <h4 class="muted small" style="text-transform:uppercase;letter-spacing:.08em;margin:18px 0 6px">So sánh công trình liên quan</h4>
    ${tableHtml(d.literature?.comparison_rows, [["key", "Bài"], ["approach", "Phương pháp"], ["limitation", "Hạn chế"]]) || '<p class="muted">Chưa có.</p>'}`;
}

async function renderTodoTab() {
  try {
    const txt = await (await api(fileOf("TODO.md").url)).text();
    const html = txt.split("\n").map((l) => {
      if (/^#\s/.test(l)) return "";
      const m = l.match(/^(\s*)-\s+(\[[ x]\]\s+)?(.*)$/);
      if (!m) return l.trim() ? `<p>${esc(l)}</p>` : "";
      const inline = esc(m[3]).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
      const pad2 = m[1].length ? "margin-left:22px;" : "";
      return `<p style="${pad2}">${m[2] ? "☐ " : "• "}${inline}</p>`;
    }).join("");
    return `<div class="prose todo-note"><div class="notice" style="margin-bottom:14px"><p>Danh sách những việc bạn cần tự kiểm tra hoặc điền trước khi sử dụng bài báo.</p></div>${html}</div>`;
  } catch (e) { return `<div class="empty">Không đọc được TODO.md: ${esc(e.message)}</div>`; }
}

function renderFilesTab() {
  const imgs = state.files.filter((f) => f.type === "image/png");
  const gallery = imgs.length ? `<div class="gallery">${imgs.map((f) =>
    `<figure class="fig" data-src="${f.url}" data-name="${esc(f.name)}"><img src="${f.url}" alt="${esc(f.name)}" loading="lazy"><figcaption>${esc(f.name)}</figcaption></figure>`).join("")}</div>` : "";
  const ico = (f) => (f.type === "image/png" ? "image" : f.name.endsWith(".zip") ? "zip" : "file");
  const list = state.files.map((f) => `<li class="file"><span class="file-ico">${icon(ico(f))}</span>
    <div class="grow"><div class="file-name">${esc(f.name)}</div><div class="file-sub">${fmtSize(f.size || 0)}</div></div>
    <a class="btn btn-sm" href="${f.url}" download>${icon("download")}Tải</a></li>`).join("");
  return `${gallery}<ul class="files">${list || '<li class="empty">Chưa có tệp.</li>'}</ul>`;
}

// ---------------------------------------------------------------- lịch sử
async function loadHistory(manual) {
  const el = $("history");
  if (!el.children.length) el.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
  try {
    const { runs } = await (await api("/api/runs?limit=20")).json();
    if (!runs.length) { el.innerHTML = '<div class="empty">Chưa có lần chạy nào.<br><span class="small">Hãy bắt đầu với một chủ đề nghiên cứu.</span></div>'; return; }
    el.innerHTML = runs.map((r) => {
      const running = ["running", "pending", "paused"].includes(r.status);
      const tone = running ? "tag-brand" : ["done", "completed"].includes(r.status) ? "tag-ok" : "tag-bad";
      return `<button type="button" class="hitem ${r.run_id === state.runId ? "current" : ""}" data-id="${r.run_id}">
        <div class="hitem-topic">${esc(r.topic || "(không có chủ đề)")}</div>
        ${running ? `<div class="mini-bar"><span style="width:${+r.progress || 0}%"></span></div>` : ""}
        <div class="hitem-meta"><span class="tag ${tone}">${esc(STATUS_LABEL[r.status] || r.status)}</span>
          ${r.compile_ok === true ? '<span class="tag">PDF</span>' : ""}<span>${esc(timeAgo(r.created_at))}</span></div></button>`;
    }).join("");
    if (manual) toast("Đã làm mới lịch sử.");
  } catch (e) { el.innerHTML = `<div class="empty">Không tải được lịch sử.<br><span class="small">${esc(e.message)}</span></div>`; }
}

async function viewRun(runId) {
  try {
    const d = await (await api(`/api/runs/${runId}`)).json();
    closeStream(); state.runId = runId; state.live = {};
    $("errorPanel").hidden = true;
    if (["running", "pending", "paused"].includes(d.status)) {
      showProgress(d.topic, d); setBusy(true);
      startTimer(d.created_at ? new Date(d.created_at).getTime() : Date.now()); subscribe(runId);
    } else {
      $("progressPanel").hidden = true; stopTimer(); setBusy(false);
      if (["error", "failed"].includes(d.status)) showError(d.error || "Lần chạy này đã thất bại.");
      await showRun(runId);
      $("resultsPanel").scrollIntoView({ behavior: "smooth", block: "start" });
    }
    loadHistory();
  } catch (e) { toast(e.message, "error"); }
}

// ---------------------------------------------------------------- khởi động
initTheme(); initForm(); setBusy(false); initHealth(); loadHistory();
$("history").addEventListener("click", (ev) => { const b = ev.target.closest(".hitem"); if (b) viewRun(b.dataset.id); });
setInterval(() => { if (!document.hidden && state.es) loadHistory(); }, 10000);

STATUS_LABEL.paused = "Tạm dừng";

function ensureRunControls() {
  if ($("runControls")) return;
  const controls = document.createElement("div");
  controls.id = "runControls"; controls.className = "actions compact-actions";
  controls.innerHTML = '<button id="pauseBtn" class="btn" type="button">Tạm dừng</button><button id="deleteRunBtn" class="btn btn-danger" type="button">Xoá nghiên cứu</button>';
  $("stageMsg").after(controls);
  $("pauseBtn").addEventListener("click", togglePause);
  $("deleteRunBtn").addEventListener("click", () => deleteRun());
}

function updateRunControls(status) {
  ensureRunControls();
  const paused = status === "paused";
  $("pauseBtn").textContent = paused ? "Tiếp tục" : "Tạm dừng";
  $("pauseBtn").dataset.action = paused ? "resume" : "pause";
  $("pauseBtn").disabled = !["running", "pending", "paused"].includes(status);
}

async function togglePause() {
  if (!state.runId) return;
  const action = $("pauseBtn").dataset.action || "pause";
  try {
    const result = await (await api(`/api/runs/${state.runId}/${action}`, { method: "POST" })).json();
    updateRunControls(result.status);
    if (result.status === "paused") { stopTimer(); $("stageMsg").textContent = "Đã tạm dừng sau bước hiện tại."; }
    else { startTimer(state.startedAt); $("stageMsg").textContent = "Đang tiếp tục nghiên cứu…"; }
    loadHistory();
  } catch (e) { toast(e.message, "error"); }
}

async function deleteRun(runId = state.runId) {
  if (!runId || !confirm("Xoá vĩnh viễn nghiên cứu này và toàn bộ tệp kết quả? Hành động này không thể hoàn tác.")) return;
  try {
    await api(`/api/runs/${runId}`, { method: "DELETE" });
    if (state.runId === runId) {
      closeStream(); stopTimer(); state.runId = null;
      $("progressPanel").hidden = true; $("resultsPanel").hidden = true; $("errorPanel").hidden = true; setBusy(false);
    }
    toast("Đã xoá vĩnh viễn lịch sử nghiên cứu.", "success"); originalLoadHistory(true);
  } catch (e) { toast(e.message, "error"); }
}

const originalShowProgress = showProgress;
showProgress = function (topic, detail) {
  originalShowProgress(topic, detail); updateRunControls(detail?.status || "running");
};

const originalHandleEvent = handleEvent;
handleEvent = function (event) {
  if (event.type === "status") {
    updateRunControls(event.status);
    if (event.status === "paused") { stopTimer(); $("stageMsg").textContent = event.message || "Đã tạm dừng."; }
    else if (event.status === "running" && event.message) $("stageMsg").textContent = event.message;
    return;
  }
  originalHandleEvent(event);
};

const originalLoadHistory = loadHistory;
loadHistory = async function (manual) {
  await originalLoadHistory(manual);
  document.querySelectorAll(".hitem").forEach((item) => {
    if (item.querySelector(".history-delete")) return;
    const del = document.createElement("span"); del.className = "history-delete";
    del.dataset.deleteId = item.dataset.id; del.textContent = "Xoá"; del.title = "Xoá vĩnh viễn";
    item.appendChild(del);
  });
};

$("history").addEventListener("click", (event) => {
  const del = event.target.closest("[data-delete-id]");
  if (del) { event.preventDefault(); event.stopImmediatePropagation(); deleteRun(del.dataset.deleteId); }
}, true);
