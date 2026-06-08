  /**
   * Table renderer for serialized tabular export nodes.
   */
  function renderTable(node) {
    const table = el("table", { className: "export-table" });
    const columns = node.columns || [];
    const rows = (node.rows || []).slice();
    const sortState = {
      column: null,
      direction: "asc",
    };

    function parseSortableNumber(value) {
      const text = value == null ? "" : String(value).trim();
      if (!text) {
        return null;
      }
      let candidate = text.replace(/,/g, "");
      let sign = 1;
      const parenthesized = candidate.match(/^\((.*)\)$/);
      if (parenthesized) {
        sign = -1;
        candidate = parenthesized[1];
      }
      candidate = candidate.replace(/^\$/, "");
      candidate = candidate.replace(/%$/, "");
      if (!/^-?\d+(\.\d+)?$/.test(candidate)) {
        return null;
      }
      return sign * Number(candidate);
    }

    function compareCellValues(leftValue, rightValue) {
      const leftNumber = parseSortableNumber(leftValue);
      const rightNumber = parseSortableNumber(rightValue);
      if (leftNumber !== null && rightNumber !== null) {
        return leftNumber - rightNumber;
      }
      return String(leftValue == null ? "" : leftValue).localeCompare(
        String(rightValue == null ? "" : rightValue),
        undefined,
        { numeric: true, sensitivity: "base" }
      );
    }

    function sortRows(column, direction) {
      rows.sort((leftRow, rightRow) => {
        const comparison = compareCellValues(leftRow[column], rightRow[column]);
        if (comparison !== 0) {
          return direction === "asc" ? comparison : -comparison;
        }
        return 0;
      });
    }

    function updateHeaderState() {
      for (const headerButton of table.querySelectorAll(".export-table-sort")) {
        const isActive = headerButton.getAttribute("data-column") === sortState.column;
        const direction = isActive ? sortState.direction : "none";
        const indicator = headerButton.querySelector(".export-table-sort-indicator");
        headerButton.setAttribute("aria-sort", direction);
        if (indicator) {
          indicator.textContent = (
            direction === "asc"
              ? "▲"
              : direction === "desc"
                ? "▼"
                : "↕"
          );
        }
      }
    }

    function renderBody() {
      const tbody = document.createElement("tbody");
      for (const row of rows) {
        const tr = document.createElement("tr");
        for (const column of columns) {
          const value = row[column];
          tr.appendChild(
            el("td", {
              text: value == null ? "" : String(value),
            })
          );
        }
        tbody.appendChild(tr);
      }
      const existing = table.querySelector("tbody");
      if (existing) {
        table.replaceChild(tbody, existing);
      } else {
        table.appendChild(tbody);
      }
    }

    function toggleSort(column) {
      if (sortState.column === column) {
        sortState.direction = sortState.direction === "asc" ? "desc" : "asc";
      } else {
        sortState.column = column;
        sortState.direction = "asc";
      }
      sortRows(column, sortState.direction);
      renderBody();
      updateHeaderState();
    }

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const column of columns) {
      const button = el("button", {
        className: "export-table-sort",
        attrs: {
          type: "button",
          "data-column": column,
          "aria-sort": "none",
        },
      }, [
        el("span", { className: "export-table-sort-label", text: column }),
        el("span", { className: "export-table-sort-indicator", text: "↕" }),
      ]);
      button.addEventListener("click", () => {
        toggleSort(column);
      });
      headRow.appendChild(el("th", {}, [button]));
    }
    thead.appendChild(headRow);
    table.appendChild(thead);
    renderBody();
    updateHeaderState();

    return el("div", { className: "table-wrap" }, [table]);
  }
