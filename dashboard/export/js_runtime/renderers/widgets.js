  /**
   * Widget renderers for export payload nodes.
   */

  function resolveWidgetValue(node, context, leafPageId) {
    if (!(node.export_enabled && node.selector_id && leafPageId)) {
      return node.value;
    }
    const pageSelectorState = getPageSelectorState(context.state, leafPageId);
    const runtimeValue = pageSelectorState[node.selector_id];
    if (
      runtimeValue !== undefined
      && runtimeValue !== null
      && (node.options || []).indexOf(runtimeValue) !== -1
    ) {
      return runtimeValue;
    }
    return node.value;
  }

  function isVmtGeographyTypeUnavailable(node, context, leafPageId) {
    if (leafPageId !== "vmt") {
      return false;
    }
    const selectorPrefixes = {
      personal_auto_vmt_geography_type: "personal_auto_vmt",
      non_motorized_vmt_geography_type: "non_motorized_vmt",
    };
    const prefix = selectorPrefixes[node.selector_id];
    if (!prefix) return false;
    const pageSelectorState = getPageSelectorState(context.state, leafPageId);
    return pageSelectorState[`${prefix}_breakdown`] !== "Home Geography";
  }

  function isWidgetDisabled(node, context, leafPageId) {
    return !!node.disabled || isVmtGeographyTypeUnavailable(node, context, leafPageId);
  }

  function selectorChangeOptions(node, leafPageId) {
    if (
      leafPageId === "vmt"
      && (
        node.selector_id === "personal_auto_vmt_breakdown"
        || node.selector_id === "non_motorized_vmt_breakdown"
      )
    ) {
      return {};
    }
    return { preferPartialRegionUpdate: true };
  }

  function renderWidget(node, context, actions, leafPageId) {
    const wrapper = el("div", { className: "widget-shell" }, [
      el("div", {
        className: "widget-label",
        text: node.name || "",
      }),
    ]);
    const effectiveValue = resolveWidgetValue(node, context, leafPageId);

    if (node.widget_type === "select") {
      const select = document.createElement("select");
      select.disabled = isWidgetDisabled(node, context, leafPageId);
      for (const option of node.options || []) {
        const opt = document.createElement("option");
        opt.value = option;
        opt.textContent = option;
        if (option === effectiveValue) {
          opt.selected = true;
        }
        select.appendChild(opt);
      }
      if (node.export_enabled && node.selector_id) {
        select.addEventListener("change", () => {
          actions.setPageSelector(
            node.selector_id,
            select.value,
            selectorChangeOptions(node, leafPageId)
          );
        });
      }
      wrapper.appendChild(select);
      return wrapper;
    }

    if (node.widget_type === "radio_button_group") {
      wrapper.appendChild(
        el("div", { className: "widget-radio-options" }, (node.options || []).map((option) => {
          return makeButton({
            label: option,
            active: option === effectiveValue,
            disabled: !!node.disabled,
            onClick: () => {
              if (node.export_enabled && node.selector_id) {
                actions.setPageSelector(node.selector_id, option);
              }
            },
            className: "widget-radio-option",
          });
        }))
      );
      return wrapper;
    }

    if (node.widget_type === "checkbox") {
      const label = document.createElement("label");
      label.className = "widget-checkbox";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.disabled = !!node.disabled;
      checkbox.checked = effectiveValue === true || effectiveValue === "True";
      checkbox.setAttribute("aria-label", node.name || "Checkbox");
      checkbox.addEventListener("change", () => {
        if (node.export_enabled && node.selector_id) {
          actions.setPageSelector(node.selector_id, checkbox.checked ? "True" : "False", {
            preferPartialRegionUpdate: true,
          });
        }
      });
      label.appendChild(checkbox);
      wrapper.appendChild(label);
      return wrapper;
    }

    fail(
      "Unknown widget type encountered in export payload:",
      node.widget_type,
      "UNKNOWN_WIDGET_TYPE"
    );
  }
