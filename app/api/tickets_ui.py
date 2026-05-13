import json
from datetime import datetime, timezone
from typing import Any

from app.models.ticket import Ticket


def render_ticket_panel_ui(secret_token: str) -> str:
    token = json.dumps(secret_token)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Открытые тикеты</title>
  <style>
    :root {{
      --bg: #000;
      --panel: #050505;
      --line: #1f1f1f;
      --line-strong: #303030;
      --text: #f2f2f2;
      --muted: #8a8a8a;
      --green: #37e06f;
      --green-dim: #12351f;
      --red: #ff6b5f;
      --radius: 16px;
      --radius-sm: 10px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", sans-serif;
      letter-spacing: 0;
    }}
    button, input, select {{ font: inherit; }}
    .shell {{
      width: min(1240px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 24px 0 36px;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-end;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: var(--radius) var(--radius) 0 0;
      background: #030303;
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      line-height: 1.1;
      font-weight: 700;
    }}
    .updated {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .controls {{
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      flex: 1 1 720px;
    }}
    .field {{
      height: 38px;
      border: 1px solid var(--line-strong);
      background: #030303;
      color: var(--text);
      border-radius: var(--radius-sm);
      padding: 0 10px;
      outline: none;
    }}
    .field:focus {{ border-color: var(--green); }}
    .search {{
      width: clamp(420px, 44vw, 620px);
      flex: 1 1 420px;
    }}
    .button {{
      height: 38px;
      border: 1px solid var(--green);
      background: #000;
      color: var(--green);
      padding: 0 12px;
      cursor: pointer;
      border-radius: var(--radius-sm);
      font-weight: 600;
    }}
    .button:hover {{ background: var(--green-dim); }}
    .button:disabled {{ opacity: .5; cursor: progress; }}
    .button.danger {{
      border-color: var(--line-strong);
      color: var(--red);
    }}
    .button.danger:hover {{ background: #240b09; }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      border-left: 1px solid var(--line);
      border-right: 1px solid var(--line);
      background: #020202;
    }}
    .metric {{
      padding: 16px 14px;
      border-right: 1px solid var(--line);
    }}
    .metric:last-child {{ border-right: 0; }}
    .metric strong {{
      display: block;
      font-size: 24px;
      line-height: 1;
      color: var(--green);
    }}
    .metric span {{
      display: block;
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }}
    .table-wrap {{
      border: 1px solid var(--line);
      border-top: 0;
      background: var(--panel);
      border-radius: 0 0 var(--radius) var(--radius);
      overflow: hidden;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    tr:hover td {{ background: #080808; }}
    .col-code {{ width: 120px; }}
    .col-source {{ width: 118px; }}
    .col-time {{ width: 164px; }}
    .col-status {{ width: 148px; }}
    .col-actions {{ width: 168px; }}
    .badge {{
      display: inline-block;
      border: 1px solid var(--line-strong);
      color: var(--text);
      padding: 4px 8px;
      font-size: 13px;
      line-height: 1.1;
      white-space: nowrap;
      border-radius: 999px;
    }}
    .badge.green {{
      border-color: var(--green);
      color: var(--green);
    }}
    .text {{
      max-height: 72px;
      overflow: hidden;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    .muted {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 5px;
      overflow-wrap: anywhere;
    }}
    .user-name {{
      margin-top: 7px;
      color: var(--text);
      font-size: 14px;
      font-weight: 700;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }}
    .actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      border: 1px solid var(--green);
      color: var(--green);
      background: #000;
      padding: 0 12px;
      text-decoration: none;
      font-weight: 600;
      border-radius: var(--radius-sm);
    }}
    .link:hover {{ background: var(--green-dim); }}
    .empty, .error {{
      padding: 34px 14px;
      text-align: center;
      color: var(--muted);
    }}
    .error {{ color: var(--red); }}
    @media (max-width: 880px) {{
      .header {{ display: block; }}
      .controls {{ justify-content: flex-start; margin-top: 16px; }}
      .search {{ width: 100%; }}
      .summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .metric:nth-child(2) {{ border-right: 0; }}
      .metric:nth-child(1), .metric:nth-child(2) {{ border-bottom: 1px solid var(--line); }}
      table, thead, tbody, tr, th, td {{ display: block; }}
      thead {{ display: none; }}
      tr {{ border-bottom: 1px solid var(--line); padding: 10px 0; }}
      tr:last-child {{ border-bottom: 0; }}
      td {{ border: 0; padding: 8px 12px; }}
      td::before {{
        content: attr(data-label);
        display: block;
        color: var(--muted);
        font-size: 11px;
        text-transform: uppercase;
        margin-bottom: 4px;
      }}
      .col-code, .col-source, .col-time, .col-status, .col-actions {{ width: auto; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="header">
      <div>
        <h1>Открытые тикеты</h1>
        <div class="updated" id="updated">Загрузка</div>
      </div>
      <div class="controls">
        <input class="field search" id="search" placeholder="Поиск по коду, пользователю, тексту">
        <select class="field" id="status">
          <option value="">Все статусы</option>
          <option value="new">Новые</option>
          <option value="reacted">Ждут ответа</option>
          <option value="answered">Ждут закрытия</option>
        </select>
        <select class="field" id="source">
          <option value="">Все источники</option>
          <option value="direct">Директ</option>
          <option value="comment">Комментарии</option>
        </select>
        <button class="button" id="refresh" type="button">Обновить</button>
      </div>
    </section>
    <section class="summary" id="summary"></section>
    <section class="table-wrap" id="table"><div class="empty">Загрузка тикетов</div></section>
  </main>
  <script>
    const TOKEN = {token};
    let tickets = [];
    const labels = {{
      new: "Новый",
      reacted: "Ждет ответа",
      answered: "Ждет закрытия",
      direct: "Директ",
      comment: "Комментарии"
    }};

    function $(id) {{ return document.getElementById(id); }}
    function escapeHtml(value) {{
      return String(value ?? "").replace(/[&<>"']/g, ch => ({{
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }}[ch]));
    }}
    function formatDate(value) {{
      if (!value) return "";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString("ru-RU", {{ dateStyle: "short", timeStyle: "short" }});
    }}
    function age(value) {{
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "";
      const minutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000));
      if (minutes < 60) return `${{minutes}} мин`;
      const hours = Math.floor(minutes / 60);
      if (hours < 24) return `${{hours}} ч ${{minutes % 60}} мин`;
      return `${{Math.floor(hours / 24)}} д ${{hours % 24}} ч`;
    }}
    function filtered() {{
      const query = $("search").value.trim().toLowerCase();
      const status = $("status").value;
      const source = $("source").value;
      return tickets.filter(ticket => {{
        if (status && ticket.status !== status) return false;
        if (source && ticket.source_type !== source) return false;
        if (!query) return true;
        return [ticket.ticket_code, ticket.display_name, ticket.username, ticket.user_id, ticket.user_message_text]
          .some(value => String(value ?? "").toLowerCase().includes(query));
      }});
    }}
    function renderSummary(list) {{
      const total = list.length;
      const newCount = list.filter(t => t.status === "new").length;
      const reacted = list.filter(t => t.status === "reacted").length;
      const answered = list.filter(t => t.status === "answered").length;
      $("summary").innerHTML = `
        <div class="metric"><strong>${{total}}</strong><span>Открыто</span></div>
        <div class="metric"><strong>${{newCount}}</strong><span>Новые</span></div>
        <div class="metric"><strong>${{reacted}}</strong><span>Ждут ответа</span></div>
        <div class="metric"><strong>${{answered}}</strong><span>Ждут закрытия</span></div>
      `;
    }}
    function render() {{
      const list = filtered();
      renderSummary(list);
      if (!list.length) {{
        $("table").innerHTML = '<div class="empty">Открытых тикетов нет</div>';
        return;
      }}
      const rows = list.map(ticket => `
        <tr>
          <td class="col-code" data-label="Тикет">
            <strong>${{escapeHtml(ticket.ticket_code || `#${{ticket.id}}`)}}</strong>
            <div class="muted">ID ${{ticket.id}}</div>
          </td>
          <td class="col-source" data-label="Источник">
            <span class="badge">${{labels[ticket.source_type] || ticket.source_type}}</span>
          </td>
          <td data-label="Сообщение">
            <div class="text">${{escapeHtml(ticket.user_message_text || "Без текста")}}</div>
            <div class="user-name">${{escapeHtml(ticket.display_name)}}</div>
          </td>
          <td class="col-time" data-label="Поступил">
            ${{formatDate(ticket.received_at_utc)}}
            <div class="muted">${{age(ticket.received_at_utc)}} назад</div>
          </td>
          <td class="col-status" data-label="Статус">
            <span class="badge green">${{labels[ticket.status] || ticket.status}}</span>
          </td>
          <td class="col-actions" data-label="Действия">
            <div class="actions">
              ${{ticket.support_url ? `<a class="link" href="${{ticket.support_url}}" target="_blank" rel="noreferrer">Перейти</a>` : ""}}
              <button class="button danger" data-close="${{ticket.id}}" type="button">Закрыть</button>
            </div>
          </td>
        </tr>
      `).join("");
      $("table").innerHTML = `
        <table>
          <thead>
            <tr>
              <th class="col-code">Тикет</th>
              <th class="col-source">Источник</th>
              <th>Сообщение</th>
              <th class="col-time">Поступил</th>
              <th class="col-status">Статус</th>
              <th class="col-actions">Действия</th>
            </tr>
          </thead>
          <tbody>${{rows}}</tbody>
        </table>
      `;
    }}
    async function loadTickets() {{
      $("refresh").disabled = true;
      try {{
        const response = await fetch("/internal/tickets/open", {{
          headers: {{ "X-Telegram-Bot-Api-Secret-Token": TOKEN }}
        }});
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.detail || "Не удалось загрузить тикеты");
        tickets = data.tickets;
        $("updated").textContent = `Обновлено: ${{new Date().toLocaleTimeString("ru-RU")}}`;
        render();
      }} catch (err) {{
        $("table").innerHTML = `<div class="error">${{escapeHtml(err.message || err)}}</div>`;
      }} finally {{
        $("refresh").disabled = false;
      }}
    }}
    async function closeTicket(id, button) {{
      if (!confirm(`Закрыть тикет #${{id}}?`)) return;
      button.disabled = true;
      try {{
        const response = await fetch(`/internal/tickets/${{id}}/close`, {{
          method: "POST",
          headers: {{ "X-Telegram-Bot-Api-Secret-Token": TOKEN }}
        }});
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.detail || "Не удалось закрыть тикет");
        tickets = tickets.filter(ticket => ticket.id !== id);
        render();
      }} catch (err) {{
        alert(err.message || err);
        button.disabled = false;
      }}
    }}
    $("refresh").addEventListener("click", loadTickets);
    $("search").addEventListener("input", render);
    $("status").addEventListener("change", render);
    $("source").addEventListener("change", render);
    document.addEventListener("click", event => {{
      const button = event.target.closest("[data-close]");
      if (!button) return;
      closeTicket(Number(button.dataset.close), button);
    }});
    loadTickets();
  </script>
</body>
</html>"""


def build_ticket_payload(ticket: Ticket, support_group_chat_id: int) -> dict[str, Any]:
    return {
        "id": ticket.id,
        "ticket_code": ticket.ticket_code,
        "status": ticket.status,
        "source_type": ticket.source_type,
        "user_id": ticket.user_id,
        "username": ticket.username,
        "display_name": ticket.display_name,
        "user_message_text": ticket.user_message_text,
        "created_at_utc": _iso(ticket.created_at_utc),
        "received_at_utc": _iso(ticket.user_message_date_utc or ticket.created_at_utc),
        "support_group_message_id": ticket.support_group_message_id,
        "support_url": build_support_message_url(support_group_chat_id, ticket.support_group_message_id),
    }


def build_support_message_url(chat_id: int, message_id: int | None) -> str | None:
    if not message_id:
        return None
    chat = str(chat_id)
    if chat.startswith("-100"):
        return f"https://t.me/c/{chat[4:]}/{message_id}"
    return None


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except Exception:
            return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
