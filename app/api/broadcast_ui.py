import json


def render_direct_broadcast_ui(webhook_secret: str = "") -> str:
    html = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Direct Broadcast</title>
  <style>
    :root {
      --bg: #111315;
      --panel: #191d20;
      --panel-2: #22282d;
      --text: #f2f2ed;
      --muted: #aeb7bc;
      --line: #343d43;
      --accent: #6ee7b7;
      --danger: #ff6b6b;
      --warn: #ffd166;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      background:
        linear-gradient(135deg, rgba(110, 231, 183, .08), transparent 34%),
        repeating-linear-gradient(90deg, rgba(255,255,255,.025) 0 1px, transparent 1px 36px),
        var(--bg);
      font-family: "Aptos", "Segoe UI", sans-serif;
    }
    main { width: min(1180px, calc(100vw - 32px)); margin: 0 auto; padding: 28px 0 44px; }
    header { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
    h1 { margin: 0; font-size: clamp(28px, 4vw, 52px); font-weight: 750; letter-spacing: 0; }
    .tag { color: var(--accent); border: 1px solid rgba(110, 231, 183, .35); padding: 8px 10px; font-size: 13px; white-space: nowrap; }
    .layout { display: grid; grid-template-columns: minmax(0, 430px) minmax(0, 1fr); gap: 18px; }
    section { background: rgba(25, 29, 32, .92); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 20px 60px rgba(0,0,0,.24); }
    .form { padding: 18px; }
    label { display: block; color: var(--muted); font-size: 13px; margin: 0 0 7px; }
    input, textarea {
      width: 100%;
      color: var(--text);
      background: #0d0f10;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 11px 12px;
      font: inherit;
      outline: none;
    }
    textarea { resize: vertical; min-height: 126px; }
    input:focus, textarea:focus { border-color: var(--accent); }
    .field { margin-bottom: 14px; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 18px; }
    button {
      border: 0;
      border-radius: 6px;
      padding: 12px 14px;
      font-weight: 700;
      cursor: pointer;
      color: #08110d;
      background: var(--accent);
    }
    button.secondary { color: var(--text); background: var(--panel-2); border: 1px solid var(--line); }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .output { min-height: 560px; overflow: hidden; }
    .bar { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 14px 16px; border-bottom: 1px solid var(--line); background: rgba(34, 40, 45, .72); }
    .status { color: var(--muted); font-size: 13px; }
    .body { padding: 14px; overflow: auto; max-height: 680px; }
    .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
    .stat { min-height: 76px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: #0d0f10; }
    .stat strong { display: block; font-size: 26px; line-height: 1; margin-bottom: 8px; }
    .stat span { color: var(--muted); font-size: 12px; }
    .ratio { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 14px; margin: 0 0 14px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: #0d0f10; }
    .ratio-track { height: 18px; display: flex; overflow: hidden; border-radius: 999px; background: rgba(255, 255, 255, .08); }
    .ratio-success { background: var(--accent); min-width: 0; }
    .ratio-failed { background: var(--danger); min-width: 0; }
    .ratio-labels { display: flex; gap: 14px; color: var(--muted); font-size: 12px; white-space: nowrap; }
    .ratio-labels strong { color: var(--text); font-size: 18px; margin-right: 4px; }
    .switcher { display: flex; gap: 8px; margin-bottom: 12px; }
    .switcher button { width: auto; min-width: 142px; padding: 9px 11px; color: var(--text); background: var(--panel-2); border: 1px solid var(--line); }
    .switcher button.active { color: #08110d; background: var(--accent); border-color: var(--accent); }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid rgba(255,255,255,.08); vertical-align: top; }
    th { color: var(--muted); font-weight: 650; }
    .pill { display: inline-block; padding: 4px 7px; border-radius: 999px; background: rgba(110, 231, 183, .12); color: var(--accent); }
    .error { color: var(--danger); }
    pre { margin: 0; white-space: pre-wrap; color: var(--muted); }
    @media (max-width: 860px) {
      header, .layout { display: block; }
      .tag { display: inline-block; margin-top: 12px; }
      .output { margin-top: 16px; }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .ratio { grid-template-columns: 1fr; }
      .ratio-labels { justify-content: space-between; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Direct Broadcast</h1>
      <div class="tag">production contour</div>
    </header>
    <div class="layout">
      <section class="form">
        <div class="field">
          <label for="secret">Webhook secret</label>
          <input id="secret" type="password" autocomplete="off">
        </div>
        <div class="field">
          <label for="usernames">Usernames</label>
          <textarea id="usernames" spellcheck="false" placeholder="@username&#10;another_username"></textarea>
        </div>
        <div class="field">
          <label for="message">Broadcast message</label>
          <textarea id="message" placeholder="Текст рассылки"></textarea>
        </div>
        <div class="row">
          <div class="field">
            <label for="delay">Interval, seconds</label>
            <input id="delay" type="number" min="0" max="60" step="0.5" value="2">
          </div>
          <div class="field">
            <label for="chat">Direct chat id filter</label>
            <input id="chat" type="text" placeholder="-207...">
          </div>
        </div>
        <div class="actions">
          <button class="secondary" id="preview">Preview</button>
          <button id="send">Start broadcast</button>
        </div>
      </section>
      <section class="output">
        <div class="bar">
          <strong>Recipients</strong>
          <span class="status" id="status">idle</span>
        </div>
        <div class="body" id="result"><pre>Run preview before sending.</pre></div>
      </section>
    </div>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const endpoint = "/internal/broadcast/direct/by-usernames";
    const initialWebhookSecret = __WEBHOOK_SECRET__;
    let lastReport = null;
    let activeList = "success";
    window.addEventListener("DOMContentLoaded", () => {
      $("secret").value = initialWebhookSecret || "";
    });

    function usernames() {
      return $("usernames").value.split(/[\\n,;]+/).map(v => v.trim()).filter(Boolean);
    }

    function payload(dryRun) {
      const chat = $("chat").value.trim();
      return {
        text: $("message").value,
        usernames: usernames(),
        direct_chat_id: chat ? Number(chat) : null,
        dry_run: dryRun,
        delay_seconds: Number($("delay").value || 0)
      };
    }

    async function submit(dryRun) {
      $("status").textContent = dryRun ? "previewing..." : "sending...";
      $("preview").disabled = true;
      $("send").disabled = true;
      try {
        const res = await fetch(endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": $("secret").value
          },
          body: JSON.stringify(payload(dryRun))
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || res.statusText);
        render(data);
        $("status").textContent = dryRun
          ? `found ${data.lookup.found.length}, missing ${data.lookup.missing.length}`
          : `sent ${data.sent}, failed ${data.failed}`;
      } catch (err) {
        $("result").innerHTML = `<pre class="error">${String(err.message || err)}</pre>`;
        $("status").textContent = "error";
      } finally {
        $("preview").disabled = false;
        $("send").disabled = false;
      }
    }

    function render(data) {
      lastReport = buildReport(data);
      activeList = lastReport.success.length ? "success" : "failed";
      renderReport();
    }

    function buildReport(data) {
      const byTopic = new Map();
      for (const item of data.lookup.found) {
        byTopic.set(`${item.chat_id}:${item.direct_messages_topic_id}`, item);
      }
      const success = [];
      const failed = [];
      const results = data.results || [];
      const sentTopics = new Set();

      for (const result of results) {
        const key = `${result.chat_id}:${result.direct_messages_topic_id}`;
        sentTopics.add(key);
        const meta = byTopic.get(key) || {};
        const row = {
          username: result.username || meta.username || "",
          first_name: meta.first_name || "",
          last_name: meta.last_name || "",
          chat_id: result.chat_id,
          direct_messages_topic_id: result.direct_messages_topic_id,
          rows: meta.rows || "",
          last_seen: meta.last_seen || "",
          status: result.status,
          reason: result.error || result.status
        };
        if (result.status === "sent" || result.status === "dry_run") success.push(row);
        else failed.push(row);
      }

      if (!results.length) {
        for (const item of data.lookup.found) {
          success.push({
            username: item.username || "",
            first_name: item.first_name || "",
            last_name: item.last_name || "",
            chat_id: item.chat_id,
            direct_messages_topic_id: item.direct_messages_topic_id,
            rows: item.rows,
            last_seen: item.last_seen || "",
            status: data.dry_run ? "dry_run" : "resolved",
            reason: data.dry_run ? "ready" : "resolved"
          });
        }
      } else {
        for (const item of data.lookup.found) {
          const key = `${item.chat_id}:${item.direct_messages_topic_id}`;
          if (!sentTopics.has(key)) {
            failed.push({
              username: item.username || "",
              first_name: item.first_name || "",
              last_name: item.last_name || "",
              chat_id: item.chat_id,
              direct_messages_topic_id: item.direct_messages_topic_id,
              rows: item.rows,
              last_seen: item.last_seen || "",
              status: "not_sent",
              reason: "resolved but no send result"
            });
          }
        }
      }

      for (const username of data.lookup.missing) {
        failed.push({ username, first_name: "", last_name: "", chat_id: "", direct_messages_topic_id: "", status: "missing", reason: "not found in Google Sheets" });
      }
      for (const item of data.lookup.ambiguous) {
        failed.push({ username: item.username, first_name: "", last_name: "", chat_id: "", direct_messages_topic_id: "", status: "ambiguous", reason: "multiple matching direct topics" });
      }

      return {
        requested: data.lookup.requested_usernames.length,
        resolved: data.lookup.found.length,
        success,
        failed,
        dry_run: data.dry_run
      };
    }

    function renderReport() {
      if (!lastReport) return;
      const list = activeList === "success" ? lastReport.success : lastReport.failed;
      const total = Math.max(lastReport.requested, 1);
      const successPct = Math.round((lastReport.success.length / total) * 100);
      const failedPct = Math.max(0, 100 - successPct);
      const rows = list.map(item => `
        <tr>
          <td><span class="pill">@${escapeHtml(item.username || "")}</span></td>
          <td>${escapeHtml([item.first_name, item.last_name].filter(Boolean).join(" "))}</td>
          <td>${item.chat_id || ""}</td>
          <td>${item.direct_messages_topic_id || ""}</td>
          <td>${escapeHtml(item.status || "")}</td>
          <td>${escapeHtml(item.reason || item.last_seen || "")}</td>
        </tr>
      `).join("");
      $("result").innerHTML = `
        <div class="stats">
          <div class="stat"><strong>${lastReport.requested}</strong><span>в списке</span></div>
          <div class="stat"><strong>${lastReport.resolved}</strong><span>найдены topic id</span></div>
          <div class="stat"><strong>${lastReport.success.length}</strong><span>${lastReport.dry_run ? "готовы" : "успешно"}</span></div>
          <div class="stat"><strong>${lastReport.failed.length}</strong><span>неуспешно</span></div>
        </div>
        <div class="ratio" aria-label="Broadcast result ratio">
          <div class="ratio-track">
            <div class="ratio-success" style="width: ${successPct}%"></div>
            <div class="ratio-failed" style="width: ${failedPct}%"></div>
          </div>
          <div class="ratio-labels">
            <span><strong>${successPct}%</strong>${lastReport.dry_run ? "готовы" : "успешно"}</span>
            <span><strong>${failedPct}%</strong>неуспешно</span>
          </div>
        </div>
        <div class="switcher">
          <button type="button" id="showSuccess" class="${activeList === "success" ? "active" : ""}">Успешные (${lastReport.success.length})</button>
          <button type="button" id="showFailed" class="${activeList === "failed" ? "active" : ""}">Неуспешные (${lastReport.failed.length})</button>
        </div>
        <table>
          <thead><tr><th>Username</th><th>Name</th><th>Chat</th><th>Topic</th><th>Status</th><th>Reason</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="6">Empty list.</td></tr>'}</tbody>
        </table>
      `;
      $("showSuccess").addEventListener("click", () => { activeList = "success"; renderReport(); });
      $("showFailed").addEventListener("click", () => { activeList = "failed"; renderReport(); });
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
      }[c]));
    }

    $("preview").addEventListener("click", () => submit(true));
    $("send").addEventListener("click", () => {
      if (confirm("Send real Telegram messages to resolved direct topics?")) submit(false);
    });
  </script>
</body>
</html>"""
    return html.replace("__WEBHOOK_SECRET__", json.dumps(webhook_secret))
