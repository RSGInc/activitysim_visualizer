  function updateActivePageSelector(selectorId, value) {
    const leafPageId = currentLeafPageId(payload, state);
    if (!leafPageId) {
      fail(
        "Cannot update a page selector because no active page is selected.",
        null,
        "MISSING_PAGE_STATE"
      );
    }
    state = updateSelectorState(state, leafPageId, selectorId, value);
    renderApp();
  }

  function renderWidget(node) {
    const wrapper = el("div", { className: "widget-shell" }, [
      el("div", {
        className: "widget-label",
        text: node.name || "",
      }),
    ]);

    if (node.widget_type === "select") {
      const select = document.createElement("select");
      select.disabled = !!node.disabled;
      (node.options || []).forEach((option) => {
        const opt = document.createElement("option");
        opt.value = option;
        opt.textContent = option;
        if (option === node.value) {
          opt.selected = true;
        }
        select.appendChild(opt);
      });
      if (node.export_enabled && node.selector_id) {
        select.addEventListener("change", () => {
          updateActivePageSelector(node.selector_id, select.value);
        });
      }
      wrapper.appendChild(select);
      return wrapper;
    }

    if (node.widget_type === "radio_button_group") {
      wrapper.appendChild(
        el("div", { className: "widget-radio-options" }, (node.options || []).map((option) => {
          return makeButton(
            option,
            {
              active: option === node.value,
              disabled: !!node.disabled,
              onClick: () => {
                if (node.export_enabled && node.selector_id) {
                  updateActivePageSelector(node.selector_id, option);
                }
              },
              className: "widget-radio-option",
            },
            null,
            "widget-radio-option"
          );
        }))
      );
      return wrapper;
    }

    fail(
      "Unknown widget type encountered in export payload:",
      node.widget_type,
      "UNKNOWN_WIDGET_TYPE"
    );
  }
