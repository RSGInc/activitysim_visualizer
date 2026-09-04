  /**
   * Plot renderer that registers serialized Plotly figures with the plot
   * lifecycle manager for later browser-side rendering.
   */
  function renderPlot(node, context) {
    const plotElement = el("div", {
      className: "plot-shell",
      attrs: { "data-plot-pending": "true" },
    });
    const aspectRatio = Number(node.aspect_ratio);
    const preserveAspectRatio = Number.isFinite(aspectRatio) && aspectRatio > 0;
    if (preserveAspectRatio) {
      plotElement.style.aspectRatio = String(aspectRatio);
    } else if (node.height) {
      plotElement.style.minHeight = String(node.height) + "px";
    }
    const baseFigure = node.figure || { data: [], layout: {} };
    const layout = Object.assign({}, baseFigure.layout || {}, {
      autosize: true,
      width: null,
    });
    if (preserveAspectRatio) {
      delete layout.height;
    }
    const figure = {
      data: baseFigure.data || [],
      layout: layout,
    };
    context.plotManager.registerPlot(plotElement, figure);
    return plotElement;
  }
