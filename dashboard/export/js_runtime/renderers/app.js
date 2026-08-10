  /**
   * Top-level app renderers.
   *
   * The app renderer translates payload pages, dashboard controls, and runtime
   * state into the final offline HTML shell shown in the browser.
   */

  function renderControlGroup(context, actions, config, isFirstGroup) {
    const group = el("div", {
      className: "control-group",
      style: {
        marginTop: isFirstGroup ? "12px" : "16px",
      },
    });
    group.appendChild(
      el("div", {
        className: "control-group-title",
        text: config.label,
      })
    );

    const chips = el("div", { className: "control-row" });
    for (const option of config.options || []) {
      chips.appendChild(
        makeButton({
          label: option,
          active: context.state[config.stateKey] === option,
          disabled: !config.enabled,
          onClick: () => {
            config.onSelect(option);
          },
          className: "toggle-chip",
        })
      );
    }
    group.appendChild(chips);
    return group;
  }

  function renderControls(context, actions) {
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

    const controlConfigs = [
      {
        label: "Weighting",
        options: context.payload.dashboard_controls.weighting,
        stateKey: "weighting",
        enabled: !!(
          context.payload.chrome
          && context.payload.chrome.controls_enabled
          && context.payload.chrome.controls_enabled.weighting
        ),
        onSelect: actions.setWeighting,
      },
      {
        label: "Values",
        options: context.payload.dashboard_controls.values,
        stateKey: "values",
        enabled: !!(
          context.payload.chrome
          && context.payload.chrome.controls_enabled
          && context.payload.chrome.controls_enabled.values
        ),
        onSelect: actions.setValues,
      },
    ];

    for (const [index, config] of controlConfigs.entries()) {
      shell.appendChild(renderControlGroup(context, actions, config, index === 0));
    }

    return shell;
  }

  function renderRunLegendItem(run) {
    const runColor = run.color || "#94a3b8";
    return el("div", {
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
  }

  function renderRunsLoaded(context) {
    const shell = el("div", { className: "rail-card" }, [
      el("h2", {
        className: "rail-section-title",
        text: "Runs Loaded",
      }),
    ]);
    const list = el("div", { className: "run-legend-list" });
    const runs = context.payload.runs_loaded || [];
    if (!runs.length) {
      list.appendChild(
        el("p", {
          className: "run-legend-empty",
          text: "No runs loaded.",
        })
      );
    } else {
      for (const run of runs) {
        list.appendChild(renderRunLegendItem(run));
      }
    }
    shell.appendChild(list);
    return shell;
  }

  function renderRailSection(context, actions, section, index) {
    if (section === "runs_loaded") {
      return [renderRunsLoaded(context)];
    }
    if (section === "display_options") {
      return [
        index > 0 ? el("div", { className: "rail-divider" }) : null,
        renderControls(context, actions),
      ];
    }
    fail(
      "Unknown rail section encountered in export payload:",
      section,
      "UNKNOWN_RAIL_SECTION"
    );
  }

  function renderRail(context, actions) {
    const rail = el("aside", { className: "export-rail" });
    const sections = (context.payload.chrome && context.payload.chrome.rail_sections) || [];
    for (const [index, section] of sections.entries()) {
      appendChildren(rail, renderRailSection(context, actions, section, index));
    }
    return rail;
  }

  function renderPageTabs(context, actions) {
    return el("div", { className: "page-tab-row" }, (context.payload.pages || []).map((page) => {
      return makeButton({
        label: page.title,
        active: page.id === context.state.activePage,
        onClick: () => {
          actions.setActivePage(page.id);
        },
        className: "page-tab-button",
      });
    }));
  }

  function renderChildPageTabs(context, actions, pageDescriptor) {
    const activeChildId = resolveActiveChildPageIdForState(pageDescriptor, context.state);
    return el("div", { className: "local-tab-row" }, (pageDescriptor.children || []).map((childPage) => {
      return makeButton({
        label: childPage.title,
        active: childPage.id === activeChildId,
        onClick: () => {
          actions.setActiveChildPage(pageDescriptor.id, childPage.id);
        },
        className: "local-tab-button",
      });
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

  function resolveActivePageNode(context) {
    const pagesForState = getPagesForCurrentState(context.payload, context.state);
    if (!pagesForState) {
      fail(
        "Missing page state for dashboard combination " + buildDashboardStateKey(context.state) + ".",
        null,
        "MISSING_PAGE_STATE"
      );
    }
    const pageDescriptor = getActivePageDescriptor(context.payload, context.state);
    if (!pageDescriptor) {
      fail(
        "Missing page descriptor for active page " + context.state.activePage + ".",
        null,
        "MISSING_PAGE_DESCRIPTOR"
      );
    }

    const leafPageId = getLeafPageId(context.payload, context.state);
    if (!leafPageId) {
      fail(
        "Missing leaf page selection for active page " + pageDescriptor.id + ".",
        null,
        "MISSING_PAGE_STATE"
      );
    }

    return {
      pageDescriptor: pageDescriptor,
      leafPageId: leafPageId,
      pageNode: pagesForState[leafPageId],
    };
  }

  function renderPagePanel(context, actions) {
    const panel = el("div", { className: "page-panel" });
    const resolvedPage = resolveActivePageNode(context);
    const pageDescriptor = resolvedPage.pageDescriptor;
    let leafPageId = resolvedPage.leafPageId;

    if (hasChildren(pageDescriptor)) {
      panel.appendChild(renderChildPageTabs(context, actions, pageDescriptor));
    }

    panel.appendChild(
      renderNode(resolvePageContent(resolvedPage.pageNode), context, actions, leafPageId)
    );
    return panel;
  }

  function renderShell(context, actions) {
    const railCollapsed = !!context.railCollapsed;
    const rail = renderRail(context, actions);
    rail.id = "export-rail";

    const main = el("main", { className: "export-main" }, [
      renderPageTabs(context, actions),
      renderPagePanel(context, actions),
    ]);
    const layout = el("div", {
      className: "export-layout" + (railCollapsed ? " rail-collapsed" : ""),
    }, [rail, main]);
    const railToggle = el("button", {
      className: "rail-toggle",
      text: railCollapsed ? "Show sidebar" : "Hide sidebar",
      attrs: {
        "aria-controls": "export-rail",
        "aria-expanded": String(!railCollapsed),
      },
    });
    railToggle.type = "button";
    railToggle.addEventListener("click", () => {
      context.railCollapsed = !context.railCollapsed;
      layout.classList.toggle("rail-collapsed", context.railCollapsed);
      railToggle.textContent = context.railCollapsed ? "Show sidebar" : "Hide sidebar";
      railToggle.setAttribute("aria-expanded", String(!context.railCollapsed));
      context.plotManager.scheduleResize();
    });

    const brandChildren = [];
    if (context.payload.logo) {
      brandChildren.push(
        el("img", {
          className: "export-logo",
          attrs: {
            src: context.payload.logo,
            alt: context.payload.title + " logo",
          },
        })
      );
    }
    brandChildren.push(el("h1", { text: context.payload.title }));

    const headerChildren = [
      el("div", { className: "export-header-top" }, [
        el("div", { className: "export-brand" }, brandChildren),
        railToggle,
      ]),
    ];
    if (context.payload.client_export_note && String(context.payload.client_export_note).trim()) {
      headerChildren.push(
        el("p", {
          className: "export-note",
          text: context.payload.client_export_note,
        })
      );
    }

    return el("div", { className: "export-shell" }, [
      el("div", { className: "export-header" }, headerChildren),
      layout,
    ]);
  }

  function renderApp(context, actions) {
    try {
      context.state = normalizeState(context.payload, context.state);
      clearRenderedRegionRegistry(context);
      clearElement(context.app);
      context.app.appendChild(renderShell(context, actions));
      context.plotManager.renderPendingPlots(context.app);
      context.plotManager.observeLayout(context.app);
      context.plotManager.scheduleResize();
    } catch (error) {
      renderRuntimeError(
        context.app,
        "This HTML export encountered a runtime rendering error.",
        error && error.message ? error.message : error
      );
    }
  }
