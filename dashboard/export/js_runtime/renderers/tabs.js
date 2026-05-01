  function renderTabs(node, leafPageId) {
    const root = document.createElement("div");
    let activeIndex = 0;
    const tabRow = el("div", { className: "local-tab-row" });
    const panel = el("div", { className: "local-tab-panel" });

    function paint() {
      clearElement(tabRow);
      clearElement(panel);
      (node.tabs || []).forEach((tab, index) => {
        tabRow.appendChild(
          makeButton(
            tab.title,
            index === activeIndex,
            () => {
              activeIndex = index;
              paint();
            },
            "local-tab-button"
          )
        );
      });
      if (node.tabs && node.tabs[activeIndex]) {
        panel.appendChild(renderNode(node.tabs[activeIndex].content, leafPageId));
      }
      requestAnimationFrame(() => {
        plotManager.renderPendingPlots(panel);
        plotManager.scheduleResize();
      });
    }

    paint();
    root.appendChild(tabRow);
    root.appendChild(panel);
    return root;
  }
