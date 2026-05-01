  function el(tag, options, children) {
    const element = document.createElement(tag);
    const config = options || {};
    const childNodes = children || [];

    if (config.className) {
      element.className = config.className;
    }
    if (config.text !== undefined && config.text !== null) {
      element.textContent = String(config.text);
    }
    if (config.attrs) {
      Object.entries(config.attrs).forEach(([name, value]) => {
        if (value !== undefined && value !== null) {
          element.setAttribute(name, String(value));
        }
      });
    }
    if (config.style) {
      Object.entries(config.style).forEach(([name, value]) => {
        if (value !== undefined && value !== null) {
          element.style[name] = String(value);
        }
      });
    }

    appendChildren(element, childNodes);
    return element;
  }

  function appendChildren(parent, children) {
    (children || []).forEach((child) => {
      if (child !== undefined && child !== null) {
        parent.appendChild(child);
      }
    });
    return parent;
  }

  function clearElement(element) {
    while (element && element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function makeButton(label, active, onClick, className) {
    let disabled = false;
    let resolvedLabel = label;
    let resolvedActive = !!active;
    let resolvedOnClick = onClick;
    let resolvedClassName = className;

    if (typeof active === "object" && active !== null) {
      disabled = !!active.disabled;
      resolvedOnClick = active.onClick;
      resolvedClassName = active.className;
      resolvedActive = !!active.active;
      resolvedLabel = active.label || label;
    }

    const button = el("button", {
      className:
        resolvedClassName
        + (resolvedActive ? " active" : "")
        + (disabled ? " disabled" : ""),
      text: resolvedLabel,
    });
    button.type = "button";
    button.disabled = disabled;
    if (!disabled && typeof resolvedOnClick === "function") {
      button.addEventListener("click", resolvedOnClick);
    }
    return button;
  }
