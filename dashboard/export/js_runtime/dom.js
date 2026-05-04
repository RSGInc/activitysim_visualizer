  /**
   * DOM helpers used by the export runtime.
   *
   * These helpers are intentionally small and explicit so Python developers can
   * read the renderers as plain "build element tree" code.
   */

  /**
   * Create a DOM element and apply a small set of supported properties.
   */
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

  /**
   * Append child nodes while ignoring null placeholders produced by render code.
   */
  function appendChildren(parent, children) {
    for (const child of children || []) {
      if (child !== undefined && child !== null) {
        parent.appendChild(child);
      }
    }
    return parent;
  }

  /**
   * Remove all current children before repainting a container.
   */
  function clearElement(element) {
    while (element && element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  /**
   * Build a button from a single config object.
   *
   * The previous overloaded helper accepted multiple call styles, which made
   * call sites harder to scan. The runtime now uses one explicit API.
   */
  function makeButton(config) {
    const button = el("button", {
      className:
        (config.className || "")
        + (config.active ? " active" : "")
        + (config.disabled ? " disabled" : ""),
      text: config.label,
    });
    button.type = "button";
    button.disabled = !!config.disabled;
    if (!config.disabled && typeof config.onClick === "function") {
      button.addEventListener("click", config.onClick);
    }
    return button;
  }
