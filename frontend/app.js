const $ = (id) => document.getElementById(id);
let currentRunId = null;
let currentResults = {};

$("startBtn").addEventListener("click", startRun);

// Khởi động: tải lịch sử
loadHistory();

// ---------- Bắt đầu run mới ----------
async function startRun() {
  const topic = $("topic").value.trim();
  if (topic.length < 5) return alert("Chủ đề quá ngắn");

  $("progressPanel").hidden = false;
  $("resultsPanel").hidden = true;
  $("errorPanel").hidden = true;
  $("progressFill").style.width = "0%";
  $("stageMsg").textContent = "Đang khởi tạo...";
  $("pdfBanner").hidden = true;
  $("pdfPreview").hidden = true;
  $("figureGallery").innerHTML = "";
  document.querySelectorAll(".stage").forEach(el =>
    el.classList.remove("active", "done")
  );
  $("startBtn").disabled = true;
  $("startBtn").textContent = "⏳ Đang chạy...";

  try {
    const res = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic,
        num_papers: +$("numPapers").value,
        max_hypotheses: +$("maxHyp").value,
        model: $("model").value,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail ? JSON.stringify(body.detail) : "Không thể tạo run");
    }
    const { run_id } = await res.json();
    currentRunId = run_id;
    subscribe(run_id);
  } catch (e) {
    showError(e.message);
    resetButton();
  }
}

// ---------- SSE ----------
function subscribe(runId) {
  const es = new EventSource(`/api/runs/${runId}/stream`);
  currentResults = {};

  es.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    handleEvent(data, es);
  };
  es.onerror = () => es.close();
}

function handleEvent(e, es) {
  if (e.type === "stage") {
    $("stageMsg").textContent = e.message;
    $("progressFill").style.width = e.progress + "%";
    document.querySelectorAll(".stage").forEach(el => {
      el.classList.remove("active");
      if (el.dataset.stage === e.stage) el.classList.add("active");
    });
  } else if (e.type === "stage_done") {
    const el = document.querySelector(`.stage[data-stage="${e.stage}"]`);
    if (el) {
      el.classList.remove("active");
      el.classList.add("done");
    }

    if (e.stage === "literature") {
      currentResults["Literature"] =
        `Tìm được ${e.num_papers} bài báo\n\n` +
        `=== TÓM TẮT ===\n${e.preview}\n\n=== RESEARCH GAP ===\n${e.gap}`;
    } else if (e.stage === "hypothesis") {
      currentResults["Hypotheses"] = e.preview;
    } else if (e.stage === "compile") {
      showPdfBanner(e.compile_ok, e.preview, currentRunId);
    } else if (e.stage === "review") {
      currentResults["Peer Review"] = e.preview;
    }
  } else if (e.type === "done") {
    es.close();
    $("stageMsg").textContent = "Hoàn thành!";
    $("progressFill").style.width = "100%";
    renderResults(currentResults);
    loadRunExtras(currentRunId);
    loadHistory();
    resetButton();
  } else if (e.type === "error") {
    es.close();
    showError(e.error);
    resetButton();
    loadHistory();
  }
}

function resetButton() {
  $("startBtn").disabled = false;
  $("startBtn").textContent = "Bắt đầu nghiên cứu";
}

// ---------- PDF banner (kèm nút tải PDF nổi bật) ----------
function showPdfBanner(ok, extraMsg, runId) {
  const el = $("pdfBanner");
  el.hidden = false;
  if (ok) {
    el.className = "pdf-banner ok";
    const dl = runId
      ? ` <a class="pdf-download-btn" href="/api/runs/${runId}/files/paper.pdf" download="paper.pdf">⬇ Tải bài báo (PDF)</a>`
      : "";
    el.innerHTML =
      "✓ Bài báo PDF đã sẵn sàng (đã chèn hình, bảng, trích dẫn & danh mục tham khảo)." + dl +
      (extraMsg ? `<div class="pdf-sub">${escapeHtml(extraMsg)}</div>` : "");
  } else {
    el.className = "pdf-banner warn";
    el.textContent = "⚠ Chưa tạo được PDF. " + (extraMsg || "Xem chi tiết ở phần Tải xuống.");
  }
}

// ---------- Render kết quả (text tabs) ----------
function renderResults(results) {
  $("resultsPanel").hidden = false;
  const tabsEl = $("resultsTabs");
  const contentEl = $("resultsContent");
  tabsEl.innerHTML = "";
  contentEl.innerHTML = "";

  const keys = Object.keys(results);
  if (keys.length === 0) {
    contentEl.innerHTML = "<p>Chưa có kết quả.</p>";
    return;
  }

  keys.forEach((k, i) => {
    const tab = document.createElement("div");
    tab.className = "tab" + (i === 0 ? " active" : "");
    tab.textContent = k;
    tab.onclick = () => {
      document
        .querySelectorAll(".tab")
        .forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      contentEl.innerHTML = `<pre>${escapeHtml(results[k])}</pre>`;
    };
    tabsEl.appendChild(tab);
  });
  contentEl.innerHTML = `<pre>${escapeHtml(results[keys[0]])}</pre>`;
}

// ---------- Figures + Files + PDF preview (sau khi run xong) ----------
async function loadRunExtras(runId) {
  await loadFiles(runId);
  await loadDetailTables(runId);
}

async function loadFiles(runId) {
  try {
    const res = await fetch(`/api/runs/${runId}/files`);
    const { files } = await res.json();
    const ul = $("fileList");
    ul.innerHTML = "";
    if (files.length === 0) {
      ul.innerHTML = "<li>Chưa có file</li>";
      return;
    }
    files.forEach((f) => {
      const li = document.createElement("li");
      li.innerHTML = `
        <span>📄 ${f.name}</span>
        <a href="${f.url}" download>Tải (${(f.size / 1024).toFixed(1)} KB)</a>
      `;
      ul.appendChild(li);
    });

    // Hình ảnh -> gallery
    const gallery = $("figureGallery");
    gallery.innerHTML = "";
    files.filter((f) => f.type === "image/png").forEach((f) => {
      const fig = document.createElement("figure");
      fig.innerHTML = `<img src="${f.url}" alt="${f.name}" loading="lazy"><figcaption>${f.name}</figcaption>`;
      gallery.appendChild(fig);
    });

    // PDF -> preview iframe
    const pdf = files.find((f) => f.name === "paper.pdf");
    const pdfPreview = $("pdfPreview");
    if (pdf) {
      $("pdfFrame").src = pdf.url;
      pdfPreview.hidden = false;
    } else {
      pdfPreview.hidden = true;
    }
  } catch (e) {
    console.error(e);
  }
}

// Lấy bảng so sánh (Table 1) + kế hoạch đánh giá (Table 2) làm tab riêng, dễ đọc hơn LaTeX thô
async function loadDetailTables(runId) {
  try {
    const res = await fetch(`/api/runs/${runId}`);
    if (!res.ok) return;
    const d = await res.json();
    const extra = {};

    if (d.literature?.comparison_rows?.length) {
      extra["Bảng 1: So sánh"] = renderRowsAsText(
        d.literature.comparison_rows,
        ["key", "approach", "limitation"]
      );
    }
    if (d.eval_rows?.length) {
      extra["Bảng 2: Kế hoạch đánh giá"] = renderRowsAsText(
        d.eval_rows,
        ["hypothesis", "baseline", "metric", "dataset"]
      );
    }
    if (d.sections?.length) {
      let txt = "";
      d.sections.forEach((s) => {
        txt += `\n\n=== ${s.name.toUpperCase()} ===\n${s.content}`;
      });
      extra["Paper Sections"] = txt.trim();
    }

    currentResults = { ...currentResults, ...extra };
    renderResults(currentResults);
  } catch (e) {
    console.error(e);
  }
}

function renderRowsAsText(rows, fields) {
  return rows.map((r) => fields.map((f) => `${f}: ${r[f] ?? ""}`).join("  |  ")).join("\n\n");
}

// ---------- History ----------
async function loadHistory() {
  try {
    const res = await fetch("/api/runs?limit=20");
    const { runs } = await res.json();
    const el = $("history");
    if (runs.length === 0) {
      el.innerHTML = "<p style='color:#94a3b8'>Chưa có run nào.</p>";
      return;
    }
    el.innerHTML = runs
      .map(
        (r) => `
      <div class="history-item">
        <div>
          <div class="hist-topic">${escapeHtml(r.topic || "")}</div>
          <div class="hist-meta">
            <span class="badge ${r.status}">${r.status}</span>
            · ${r.progress}% · ${formatDate(r.created_at)}
            ${r.compile_ok === true ? '<span class="badge done">PDF ✓</span>' : ""}
            ${r.compile_ok === false ? '<span class="badge error">PDF ✗</span>' : ""}
          </div>
        </div>
        <button class="view-btn" data-id="${r.run_id}">Xem</button>
      </div>
    `
      )
      .join("");

    el.querySelectorAll(".view-btn").forEach((b) =>
      b.addEventListener("click", () => viewRun(b.dataset.id))
    );
  } catch (e) {
    console.error(e);
  }
}

// ---------- Xem lại run cũ ----------
async function viewRun(runId) {
  try {
    const res = await fetch(`/api/runs/${runId}`);
    if (!res.ok) throw new Error("Không tìm thấy run");
    const d = await res.json();

    const results = {};
    if (d.literature) {
      const n = d.literature.papers?.length || 0;
      results["Literature"] =
        `${n} bài báo\n\n` +
        `=== TÓM TẮT ===\n${d.literature.summaries || ""}\n\n` +
        `=== RESEARCH GAP ===\n${d.literature.research_gap || ""}`;
      if (d.literature.comparison_rows?.length) {
        results["Bảng 1: So sánh"] = renderRowsAsText(
          d.literature.comparison_rows, ["key", "approach", "limitation"]
        );
      }
    }
    if (d.hypotheses) results["Hypotheses"] = d.hypotheses;
    if (d.eval_rows?.length) {
      results["Bảng 2: Kế hoạch đánh giá"] = renderRowsAsText(
        d.eval_rows, ["hypothesis", "baseline", "metric", "dataset"]
      );
    }
    if (d.sections?.length) {
      let txt = "";
      d.sections.forEach((s) => {
        txt += `\n\n=== ${s.name.toUpperCase()} ===\n${s.content}`;
      });
      results["Paper Sections"] = txt.trim();
    }
    if (d.review) results["Peer Review"] = d.review;

    $("resultsPanel").hidden = false;
    $("errorPanel").hidden = true;
    currentResults = results;
    renderResults(results);
    loadFiles(runId);
    if (d.compile_ok !== null && d.compile_ok !== undefined) showPdfBanner(d.compile_ok, "", runId);

    if (d.status === "running" || d.status === "pending") {
      $("progressPanel").hidden = false;
      $("progressFill").style.width = (d.progress || 0) + "%";
      $("stageMsg").textContent = d.stage || "Đang chạy...";
      currentRunId = runId;
      subscribe(runId);
      $("startBtn").disabled = true;
      $("startBtn").textContent = "⏳ Đang chạy...";
    }
  } catch (e) {
    showError(e.message);
  }
}

// ---------- Utility ----------
function showError(msg) {
  $("errorPanel").hidden = false;
  $("errorMsg").textContent = msg;
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("vi-VN");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}
