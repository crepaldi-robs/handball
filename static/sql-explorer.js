"use strict";

const sqlRoot = document.querySelector("[data-sql-explorer]");
if (sqlRoot) {
  const message = document.querySelector("#sql-message");
  const editor = document.querySelector("#sql-editor");
  const results = document.querySelector("#sql-results");
  const changePreview = document.querySelector("#sql-change-preview");
  const csrfToken = sqlRoot.dataset.csrfToken;
  let pendingToken = null;

  function show(text, kind = "success") {
    message.textContent = text;
    message.className = `alert alert-${kind}`;
    message.hidden = false;
  }
  async function request(url, options = {}) {
    const headers = { Accept: "application/json", "Content-Type": "application/json", ...(options.headers || {}) };
    if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = csrfToken;
    const response = await fetch(url, { credentials: "same-origin", ...options, headers });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `Falha HTTP ${response.status}`);
    }
    return response.json();
  }
  function renderCatalog(catalog) {
    const target = document.querySelector("#sql-relations");
    target.replaceChildren();
    for (const relation of catalog.relations) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "sql-relation";
      item.textContent = relation.restricted ? `${relation.name} · restrita` : `${relation.name} · ${relation.kind}`;
      item.disabled = relation.restricted;
      item.addEventListener("click", () => { editor.value = `SELECT *\nFROM "${relation.name.replaceAll('"', '""')}"\nLIMIT 100`; });
      target.append(item);
    }
  }
  function renderResult(payload) {
    results.replaceChildren();
    const table = document.createElement("table");
    const head = document.createElement("tr");
    for (const column of payload.columns) {
      const cell = document.createElement("th");
      cell.textContent = column;
      head.append(cell);
    }
    table.append(head);
    for (const row of payload.rows) {
      const line = document.createElement("tr");
      for (const column of payload.columns) {
        const cell = document.createElement("td");
        cell.textContent = row[column] == null ? "" : String(row[column]);
        line.append(cell);
      }
      table.append(line);
    }
    results.append(table);
    show(`${payload.rows.length} linhas na prévia${payload.has_more ? "; há mais resultados." : "."}`);
  }
  async function run(endpoint = "query") {
    pendingToken = null;
    if (changePreview) changePreview.hidden = true;
    const payload = await request(`/api/v1/sql/${endpoint}`, {
      method: "POST",
      body: JSON.stringify({ sql: editor.value, page: 1, page_size: 100 }),
    });
    if (endpoint === "explain") {
      renderResult({ columns: ["id", "parent", "notused", "detail"], rows: payload.items, has_more: false });
    } else {
      renderResult(payload);
    }
  }
  async function previewChange() {
    const payload = await request("/api/v1/sql/changes/preview", {
      method: "POST",
      body: JSON.stringify({ sql: editor.value }),
    });
    pendingToken = payload.token;
    changePreview.replaceChildren();
    const heading = document.createElement("h2");
    heading.textContent = "Prévia da alteração";
    const summary = document.createElement("p");
    const tables = payload.tables.length ? payload.tables.join(", ") : "estrutura do banco";
    summary.textContent = `${payload.operation}: ${payload.affected_rows} linha(s) diretamente afetada(s), ${payload.cascade_rows} efeito(s) em cascata. Tabelas: ${tables}.`;
    changePreview.append(heading, summary);
    if (payload.whole_table_warning) {
      const warning = document.createElement("p");
      warning.className = "alert alert-error";
      warning.textContent = "Atenção: a alteração esvaziará ao menos uma tabela.";
      changePreview.append(warning);
    }
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "button button-danger";
    confirm.textContent = "Confirmar e executar alteração";
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      try {
        const executed = await request("/api/v1/sql/changes/execute", {
          method: "POST",
          body: JSON.stringify({ token: pendingToken }),
        });
        pendingToken = null;
        changePreview.hidden = true;
        show(`Alteração executada: ${executed.affected_rows} linha(s). Backup ${executed.backup_id}.`);
      } catch (error) {
        show(error.message, "error");
        pendingToken = null;
      } finally {
        confirm.disabled = false;
      }
    });
    changePreview.append(confirm);
    changePreview.hidden = false;
    show("Prévia concluída. Revise o impacto antes de confirmar.");
  }
  async function download(format) {
    const response = await fetch(`/api/v1/sql/export/${format}`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ sql: editor.value }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "Falha na exportação.");
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `consulta.${format}`;
    link.click();
    URL.revokeObjectURL(url);
    show(`Exportação ${format.toUpperCase()} concluída.`);
  }
  document.querySelector("#sql-run").addEventListener("click", () => run().catch((error) => show(error.message, "error")));
  document.querySelector("#sql-preview-change")?.addEventListener("click", () => previewChange().catch((error) => show(error.message, "error")));
  document.querySelector("#sql-explain").addEventListener("click", () => run("explain").catch((error) => show(error.message, "error")));
  document.querySelector("#sql-csv").addEventListener("click", () => download("csv").catch((error) => show(error.message, "error")));
  document.querySelector("#sql-xlsx").addEventListener("click", () => download("xlsx").catch((error) => show(error.message, "error")));
  request("/api/v1/sql/catalog").then(renderCatalog).catch((error) => show(error.message, "error"));
}
