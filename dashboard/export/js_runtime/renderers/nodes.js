  function nodeRole(node) {
    if (!node || typeof node !== "object") {
      return "unknown";
    }
    if (node.kind === "plotly") {
      return "plot";
    }
    if (node.kind === "table") {
      return "table";
    }
    if (node.kind === "card") {
      return "card";
    }
    if (node.kind === "widget") {
      return "widget";
    }
    if (node.kind === "tabs") {
      return "tabs";
    }
    if (node.kind === "spacer") {
      return "spacer";
    }
    if (node.kind === "container") {
      return node.layout === "row" ? "row" : "column";
    }
    if (node.kind === "region") {
      return "region";
    }
    return "html";
  }

  function renderContainer(node, leafPageId) {
    const layoutClass = node.layout === "row" ? "container-row" : "container-column";
    const childCount = Number(node.child_count || (node.children || []).length || 0);
    const container = el("div", {
      className: layoutClass + " child-count-" + String(childCount),
    });
    (node.children || []).forEach((child) => {
      const wrapper = el("div", {
        className: "container-item container-item--" + nodeRole(child),
      }, [
        renderNode(child, leafPageId),
      ]);
      container.appendChild(wrapper);
    });
    return container;
  }

  function renderCard(node, leafPageId) {
    const card = el("div", { className: "card" });
    if (node.title) {
      card.appendChild(el("div", { className: "card-title", text: node.title }));
    }
    (node.children || []).forEach((child) => {
      card.appendChild(renderNode(child, leafPageId));
    });
    return card;
  }

  function renderTrustedHtml(node) {
    const div = document.createElement("div");
    // node.html is produced by dashboard-owned Python serializers.
    // Do not treat this as a safe sink for arbitrary untrusted user HTML.
    div.innerHTML = node.html || "";
    return div;
  }

  function renderSpacer(node) {
    const spacer = el("div", { className: "export-spacer" });
    if (node.height != null) {
      spacer.style.height = String(node.height) + "px";
    }
    if (node.width != null) {
      spacer.style.width = String(node.width) + "px";
    }
    return spacer;
  }

  const NODE_RENDERERS = {
    container: renderContainer,
    card: renderCard,
    html: renderTrustedHtml,
    plotly: renderPlot,
    table: renderTable,
    widget: renderWidget,
    tabs: renderTabs,
    spacer: renderSpacer,
    region: renderRegion,
  };

  function renderNode(node, leafPageId) {
    if (!node || typeof node !== "object") {
      fail("Encountered malformed export node content.", null, "INVALID_EXPORT_NODE");
    }
    const renderer = NODE_RENDERERS[node.kind];
    if (!renderer) {
      fail(
        "Unknown export node kind encountered:",
        node.kind,
        "UNKNOWN_NODE_KIND"
      );
    }
    return renderer(node, leafPageId);
  }
