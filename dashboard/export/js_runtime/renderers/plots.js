  /**
   * Plot renderer that registers serialized Plotly figures with the plot
   * lifecycle manager for later browser-side rendering.
   */
  function renderPlot(node, context) {
    const plotElement = el("div", {
      className: "plot-shell",
      attrs: { "data-plot-pending": "true" },
    });
    if (node.height) {
      plotElement.style.minHeight = String(node.height) + "px";
    }
    const baseFigure = node.figure || { data: [], layout: {} };
    const figure = {
      data: baseFigure.data || [],
      layout: Object.assign({}, baseFigure.layout || {}, {
        autosize: true,
        width: null,
      }),
    };
    context.plotManager.registerPlot(plotElement, figure);
    return plotElement;
  }
