  /**
   * Local tab renderer used inside exported pages.
   */
  function renderTabs(node, context, actions, leafPageId) {
    const root = document.createElement("div");
    let activeIndex = 0;
    const tabRow = el("div", { className: "local-tab-row" });
    const panel = el("div", { className: "local-tab-panel" });

    function paint() {
      clearElement(tabRow);
      clearElement(panel);
      for (const [index, tab] of (node.tabs || []).entries()) {
        tabRow.appendChild(
          makeButton({
            label: tab.title,
            title: tab.full_title || tab.title,
            active: index === activeIndex,
            onClick: () => {
              activeIndex = index;
              paint();
            },
            className: "local-tab-button",
          })
        );
      }
      if (node.tabs && node.tabs[activeIndex]) {
        panel.appendChild(renderNode(node.tabs[activeIndex].content, context, actions, leafPageId));
      }
      requestAnimationFrame(() => {
        context.plotManager.renderPendingPlots(panel);
        context.plotManager.scheduleResize();
      });
    }

    paint();
    root.appendChild(tabRow);
    root.appendChild(panel);
    return root;
  }
