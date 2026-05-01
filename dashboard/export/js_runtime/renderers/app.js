  function renderControls() {
    const shell = el("div", { className: "rail-card" }, [
      el("h2", {
        className: "rail-section-title",
        text: "Display Options",
      }),
      el("p", {
        className: "display-options-note",
        text: "Display mode controls.",
      }),
    ]);

    [
      ["Weighting", payload.dashboard_controls.weighting, "weighting"],
      ["Values", payload.dashboard_controls.values, "values"],
    ].forEach(([label, options, key]) => {
      const group = el("div", {
        className: "control-group",
        style: {
          marginTop: shell.children.length > 2 ? "16px" : "12px",
        },
      });
      group.appendChild(
        el("div", {
          className: "control-group-title",
          text: label,
        })
      );
      const chips = el("div", { className: "control-row" });
      const enabled = !!(
        payload.chrome
        && payload.chrome.controls_enabled
        && payload.chrome.controls_enabled[key]
      );
      (options || []).forEach((option) => {
        chips.appendChild(
          makeButton(
            option,
            {
              active: state[key] === option,
              disabled: !enabled,
              onClick: () => {
                state[key] = option;
                renderApp();
              },
              className: "toggle-chip",
            },
            null,
            "toggle-chip"
          )
        );
      });
      group.appendChild(chips);
      shell.appendChild(group);
    });

    return shell;
  }

  function renderRunsLoaded() {
    const shell = el("div", { className: "rail-card" }, [
      el("h2", {
        className: "rail-section-title",
        text: "Runs Loaded",
      }),
    ]);
    const list = el("div", { className: "run-legend-list" });
    const runs = payload.runs_loaded || [];
    if (!runs.length) {
      list.appendChild(
        el("p", {
          className: "run-legend-empty",
          text: "No runs loaded.",
        })
      );
    } else {
      runs.forEach((run) => {
        const runColor = run.color || "#94a3b8";
        const item = el("div", {
          className: "run-legend-item",
          attrs: {
            "data-run-label": run.label || "",
            "data-run-color": run.color || "",
          },
          style: {
            padding: "8px 10px",
            borderLeft: "4px solid " + runColor,
            margin: "6px 0",
            borderRadius: "6px",
            background: "rgba(127,127,127,0.06)",
          },
        }, [
          el("b", {
            text: run.label || "",
            style: {
              color: run.color || "",
            },
          }),
        ]);
        list.appendChild(item);
      });
    }
    shell.appendChild(list);
    return shell;
  }

  function renderRail() {
    const rail = el("aside", { className: "export-rail" });
    const sections = (payload.chrome && payload.chrome.rail_sections) || [];
    sections.forEach((section, index) => {
      if (section === "runs_loaded") {
        rail.appendChild(renderRunsLoaded());
        return;
      }
      if (section === "display_options") {
        if (index > 0) {
          rail.appendChild(el("div", { className: "rail-divider" }));
        }
        rail.appendChild(renderControls());
        return;
      }
      fail(
        "Unknown rail section encountered in export payload:",
        section,
        "UNKNOWN_RAIL_SECTION"
      );
    });
    return rail;
  }

  function renderPageTabs() {
    return el("div", { className: "page-tab-row" }, (payload.pages || []).map((page) => {
      return makeButton(
        page.title,
        page.id === state.activePage,
        () => {
          state.activePage = page.id;
          renderApp();
        },
        "page-tab-button"
      );
    }));
  }

  function renderChildPageTabs(pageDescriptor) {
    const activeChildId = resolveActiveChildPageId(pageDescriptor);
    return el("div", { className: "local-tab-row" }, (pageDescriptor.children || []).map((childPage) => {
      return makeButton(
        childPage.title,
        childPage.id === activeChildId,
        () => {
          state.activeChildPage[pageDescriptor.id] = childPage.id;
          renderApp();
        },
        "local-tab-button"
      );
    }));
  }

  function resolvePageContent(pageNode) {
    if (!pageNode || typeof pageNode !== "object") {
      fail(
        "Missing page state for the active dashboard selection.",
        null,
        "MISSING_PAGE_STATE"
      );
    }
    if (pageNode.kind === "page") {
      return pageNode.content;
    }
    fail(
      "Unknown page content kind encountered:",
      pageNode.kind,
      "UNKNOWN_PAGE_CONTENT"
    );
  }

  function renderPagePanel() {
    const panel = el("div", { className: "page-panel" });
    const pagesForState = payload.states[stateKey(state)];
    if (!pagesForState) {
      fail(
        "Missing page state for dashboard combination " + stateKey(state) + ".",
        null,
        "MISSING_PAGE_STATE"
      );
    }
    const pageDescriptor = findPageById(payload.pages || [], state.activePage);
    if (!pageDescriptor) {
      fail(
        "Missing page descriptor for active page " + state.activePage + ".",
        null,
        "MISSING_PAGE_DESCRIPTOR"
      );
    }

    let leafPageId = pageDescriptor.id;
    if (hasChildren(pageDescriptor)) {
      panel.appendChild(renderChildPageTabs(pageDescriptor));
      leafPageId = resolveActiveChildPageId(pageDescriptor);
    }

    panel.appendChild(renderNode(resolvePageContent(pagesForState[leafPageId]), leafPageId));
    return panel;
  }

  function renderShell() {
    const headerChildren = [
      el("h1", { text: payload.title }),
    ];
    if (payload.client_export_note && String(payload.client_export_note).trim()) {
      headerChildren.push(
        el("p", {
          className: "export-note",
          text: payload.client_export_note,
        })
      );
    }

    const main = el("main", { className: "export-main" }, [
      renderPageTabs(),
      renderPagePanel(),
    ]);

    return el("div", { className: "export-shell" }, [
      el("div", { className: "export-header" }, headerChildren),
      el("div", { className: "export-layout" }, [
        renderRail(),
        main,
      ]),
    ]);
  }

  function renderApp() {
    try {
      clearElement(app);
      app.appendChild(renderShell());
      plotManager.renderPendingPlots(app);
      plotManager.observeLayout(app);
      plotManager.scheduleResize();
    } catch (error) {
      renderRuntimeError(
        "This HTML export encountered a runtime rendering error.",
        error && error.message ? error.message : error
      );
    }
  }
