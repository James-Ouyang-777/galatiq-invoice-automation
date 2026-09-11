const $ = (sel) => document.querySelector(sel);
let runs = [];
let selectedId = null;

function money(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString(undefined, { style: "currency", currency: "USD" });
}

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 2800);
}

async function jfetch(url, opts) {
  const headers = { ...(opts && opts.headers) };
  if (opts && opts.body && !(opts.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(url, { ...opts, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || res.statusText);
  }
  return res.json();
}

async function refresh() {
  const [m, r, h] = await Promise.all([
    jfetch("/api/metrics"),
    jfetch("/api/runs"),
    jfetch("/api/health"),
  ]);
  $("#m-processed").textContent = m.processed;
  $("#m-rate").textContent = `${Math.round((m.auto_pay_rate || 0) * 100)}%`;
  $("#m-paid").textContent = money(m.paid_amount);
  $("#m-held").textContent = money(m.held_amount);
  $("#llm-badge").textContent = `LLM: ${h.llm}`;
  runs = r.runs || [];
  $("#queue-count").textContent = String(runs.length);
  renderQueue();
  if (selectedId) await showDetail(selectedId);
}

function renderQueue() {
  const ul = $("#queue");
  ul.innerHTML = "";
  if (!runs.length) {
    ul.innerHTML = `<li class="muted">Inbox is empty. Process the sample invoices.</li>`;
    return;
  }
  for (const run of runs) {
    const li = document.createElement("li");
    if (run.run_id === selectedId) li.classList.add("active");
    li.innerHTML = `
      <div><span class="id">${run.invoice_id || "—"}</span>
        <span class="chip ${run.status}">${run.status}</span></div>
      <div class="vendor">${run.vendor || run.source_path}</div>
      <div class="amt">${run.amount != null ? money(run.amount) : ""} ${run.currency || ""}</div>`;
    li.addEventListener("click", () => showDetail(run.run_id));
    ul.appendChild(li);
  }
}

async function showDetail(runId) {
  selectedId = runId;
  renderQueue();
  const run = await jfetch(`/api/runs/${runId}`);
  $("#empty-state").hidden = true;
  const body = $("#detail-body");
  body.hidden = false;
  const items = (run.invoice && run.invoice.line_items) || [];
  const flags = run.flags || [];
  const validation = run.validation || {};
  const vp = run.vp;
  const trace = run.trace || [];
  const canAct = run.status === "held" || run.status === "rejected";

  body.innerHTML = `
    <div class="detail-head">
      <div>
        <h2>${run.invoice_id || "Unparsed"}</h2>
        <div class="meta">${run.vendor || "Unknown vendor"} · ${run.amount != null ? money(run.amount) : "—"} ${run.currency || ""}
          · <span class="chip ${run.status}">${run.status}</span></div>
      </div>
      <div class="actions">
        <button class="btn primary" ${canAct ? "" : "disabled"} data-act="pay">Override &amp; Pay</button>
        <button class="btn danger" ${canAct ? "" : "disabled"} data-act="reject">Reject</button>
        <button class="btn" data-act="rerun">Re-run</button>
      </div>
    </div>
    <p class="meta">${(run.policy && run.policy.summary) || run.error || ""}</p>
    <div class="grid-2">
      <div class="card">
        <h3>Line items vs stock</h3>
        <table>
          <thead><tr><th>SKU</th><th class="num">Qty</th><th>Stock check</th></tr></thead>
          <tbody>
            ${(validation.items || []).map((it) => `
              <tr><td>${it.sku}</td><td class="num">${it.quantity}</td>
              <td>${it.message}</td></tr>`).join("") || `<tr><td colspan="3">${items.map(i => i.sku + " × " + i.quantity).join(", ") || "None"}</td></tr>`}
          </tbody>
        </table>
      </div>
      <div class="card">
        <h3>Controls</h3>
        ${flags.map((f) => `<div class="flag ${f.severity}"><strong>${f.code}</strong> — ${f.message}</div>`).join("") || `<p class="muted">No control flags. Eligible for auto-pay.</p>`}
      </div>
    </div>
    ${vp ? `<div class="card vp-box"><h3>VP review</h3>
      <div class="draft">Draft: <strong>${vp.draft_decision}</strong> — ${vp.draft_rationale}</div>
      <div>Critic ${vp.critic_agrees ? "agrees" : "revises"} → <strong>${vp.final_decision}</strong>. ${vp.final_rationale}
      ${vp.used_llm ? "" : " (heuristic fallback — no LLM key)"}</div></div>` : ""}
    <div class="card">
      <h3>Agent trace</h3>
      <ol class="trace">
        ${trace.map((t) => `<li><div class="node">${t.node}</div><div class="msg">${t.message}</div></li>`).join("")}
      </ol>
    </div>
    <p class="muted">Source: ${run.source_path}</p>
  `;

  body.querySelectorAll("[data-act]").forEach((btn) => {
    btn.addEventListener("click", () => act(run.run_id, btn.dataset.act));
  });
}

async function act(runId, kind) {
  try {
    if (kind === "pay") await jfetch(`/api/runs/${runId}/pay`, { method: "POST" });
    if (kind === "reject") await jfetch(`/api/runs/${runId}/reject`, { method: "POST" });
    if (kind === "rerun") {
      const run = await jfetch(`/api/runs/${runId}/rerun`, { method: "POST" });
      selectedId = run.run_id;
    }
    toast(kind === "pay" ? "Payment posted" : kind === "reject" ? "Rejected" : "Re-ran");
    await refresh();
  } catch (err) {
    toast(err.message);
  }
}

document.querySelectorAll("[data-demo]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      const res = await jfetch("/api/process", {
        method: "POST",
        body: JSON.stringify({ path: btn.dataset.demo }),
      });
      const run = (res.runs || [])[0];
      if (run) selectedId = run.run_id;
      toast(`Processed ${run ? run.invoice_id : btn.dataset.demo}`);
      await refresh();
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false;
    }
  });
});

$("#btn-process-all").addEventListener("click", async () => {
  const btn = $("#btn-process-all");
  btn.disabled = true;
  btn.textContent = "Processing…";
  try {
    await jfetch("/api/process-all", { method: "POST" });
    toast("Inbox processed");
    await refresh();
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Process inbox";
  }
});

$("#btn-demo").addEventListener("click", async () => {
  const btn = $("#btn-demo");
  btn.disabled = true;
  btn.textContent = "Running demo…";
  try {
    const res = await jfetch("/api/demo", { method: "POST" });
    const last = (res.runs || []).at(-1);
    if (last) selectedId = last.run_id;
    toast("Demo path complete — 1001 paid, 1002/1003 held, 1004 paid, R1 held");
    await refresh();
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Run 2-min demo";
  }
});

async function uploadFile(file) {
  const data = new FormData();
  data.append("file", file);
  toast(`Uploading ${file.name}…`);
  const res = await jfetch("/api/upload", { method: "POST", body: data });
  const run = (res.runs || [])[0];
  if (run) selectedId = run.run_id;
  toast(`${run ? run.invoice_id : file.name} → ${run ? run.status : "done"}`);
  await refresh();
}

$("#file-input").addEventListener("change", async (event) => {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  try {
    await uploadFile(file);
  } catch (err) {
    toast(err.message);
  } finally {
    event.target.value = "";
  }
});

const drop = document.querySelector(".upload-box");
["dragenter", "dragover"].forEach((name) => {
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add("hot");
  });
});
["dragleave", "drop"].forEach((name) => {
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.remove("hot");
  });
});
drop.addEventListener("drop", async (event) => {
  const file = event.dataTransfer.files && event.dataTransfer.files[0];
  if (!file) return;
  try {
    await uploadFile(file);
  } catch (err) {
    toast(err.message);
  }
});

refresh().catch((err) => toast(err.message));
