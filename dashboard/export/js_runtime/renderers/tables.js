  /**
   * Table renderer for serialized tabular export nodes.
   */
  function renderTable(node) {
    const table = el("table", { className: "export-table" });
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const column of node.columns || []) {
      headRow.appendChild(el("th", { text: column }));
    }
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const row of node.rows || []) {
      const tr = document.createElement("tr");
      for (const column of node.columns || []) {
        const value = row[column];
        tr.appendChild(
          el("td", {
            text: value == null ? "" : String(value),
          })
        );
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);

    return el("div", { className: "table-wrap" }, [table]);
  }
