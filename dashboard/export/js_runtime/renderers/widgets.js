  /**
   * Widget renderers for export payload nodes.
   */

  function resolveWidgetOptions(node, context, leafPageId) {
    if (!(node.parent_selector_id && leafPageId)) {
      return node.options || [];
    }
    const pageSelectorState = getPageSelectorState(context.state, leafPageId);
    const parentValue = pageSelectorState[node.parent_selector_id];
    const dependentOptions = (
      node.options_by_parent_value
      && node.options_by_parent_value[parentValue]
    );
    return dependentOptions || node.options || [];
  }

  function resolveWidgetValue(node, context, leafPageId, effectiveOptions) {
    if (!(node.export_enabled && node.selector_id && leafPageId)) {
      return node.value;
    }
    const pageSelectorState = getPageSelectorState(context.state, leafPageId);
    const runtimeValue = pageSelectorState[node.selector_id];
    if (
      runtimeValue !== undefined
      && runtimeValue !== null
      && effectiveOptions.indexOf(runtimeValue) !== -1
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
    if (node.parent_selector_id && leafPageId) {
      const pageSelectorState = getPageSelectorState(context.state, leafPageId);
      const parentValue = pageSelectorState[node.parent_selector_id];
      if ((node.disabled_parent_values || []).indexOf(parentValue) !== -1) {
        return true;
      }
    }
    return !!node.disabled || isVmtGeographyTypeUnavailable(node, context, leafPageId);
  }

  function selectorHasDependents(context, leafPageId, selectorId) {
    const pageDescriptor = findPageDescriptorById(
      context.payload.pages || [],
      leafPageId
    );
    return !!(
      pageDescriptor
      && (pageDescriptor.selectors || []).some((selector) => {
        return selector.parent_selector_id === selectorId;
      })
    );
  }

  function selectorChangeOptions(node, context, leafPageId) {
    if (selectorHasDependents(context, leafPageId, node.selector_id)) {
      return {};
    }
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
    const effectiveOptions = resolveWidgetOptions(node, context, leafPageId);
    const effectiveValue = resolveWidgetValue(
      node,
      context,
      leafPageId,
      effectiveOptions
    );

    if (node.widget_type === "select") {
      const select = document.createElement("select");
      select.disabled = isWidgetDisabled(node, context, leafPageId);
      for (const option of effectiveOptions) {
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
            selectorChangeOptions(node, context, leafPageId)
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

    if (node.widget_type === "float_input") {
      const input = document.createElement("input");
      input.type = "number";
      input.value = effectiveValue ?? "";
      if (node.step !== undefined && node.step !== null) {
        input.step = String(node.step);
      }
      input.disabled = isWidgetDisabled(node, context, leafPageId);
      wrapper.appendChild(input);
      return wrapper;
    }

    if (node.widget_type === "button") {
      wrapper.appendChild(
        makeButton({
          label: node.name || node.value || "",
          disabled: true,
          className: "widget-button",
        })
      );
      return wrapper;
    }

    fail(
      "Unknown widget type encountered in export payload:",
      node.widget_type,
      "UNKNOWN_WIDGET_TYPE"
    );
  }
