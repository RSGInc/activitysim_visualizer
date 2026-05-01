  function renderTable(node) {
    const table = el("table", { className: "export-table" });
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    (node.columns || []).forEach((column) => {
      headRow.appendChild(el("th", { text: column }));
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    (node.rows || []).forEach((row) => {
      const tr = document.createElement("tr");
      (node.columns || []).forEach((column) => {
        const value = row[column];
        tr.appendChild(
          el("td", {
            text: value == null ? "" : String(value),
          })
        );
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    return el("div", { className: "table-wrap" }, [table]);
  }
