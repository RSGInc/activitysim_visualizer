  function resolveRegionContent(node, leafPageId) {
    const pageSelectorState = state.pageSelectors[leafPageId] || {};
    const values = (node.selector_ids || []).map((selectorId) => {
      return pageSelectorState[selectorId];
    });
    const variantLookupKey = JSON.stringify(values);
    return (node.variants && node.variants[variantLookupKey]) || node.default_content;
  }

  function renderRegion(node, leafPageId) {
    return el("div", {
      className: "export-region",
      attrs: {
        "data-region-id": node.region_id || "",
        "data-leaf-page-id": leafPageId || "",
        "data-selector-ids": JSON.stringify(node.selector_ids || []),
      },
    }, [
      renderNode(resolveRegionContent(node, leafPageId), leafPageId),
    ]);
  }

  function collectRegionNodes(node, regions) {
    if (!node || typeof node !== "object") {
      return regions;
    }
    if (node.kind === "region") {
      regions.push(node);
      return regions;
    }
    if (node.kind === "container" || node.kind === "card") {
      (node.children || []).forEach((child) => {
        collectRegionNodes(child, regions);
      });
      return regions;
    }
    if (node.kind === "tabs") {
      (node.tabs || []).forEach((tab) => {
        collectRegionNodes(tab.content, regions);
      });
      return regions;
    }
    return regions;
  }

  function updateRenderedRegions(leafPageId, changedSelectorId) {
    const pagesForState = payload.states[stateKey(state)];
    if (!pagesForState) {
      return false;
    }
    const pageNode = pagesForState[leafPageId];
    if (!pageNode || pageNode.kind !== "page") {
      return false;
    }
    const regionNodes = collectRegionNodes(pageNode.content, []).filter((regionNode) => {
      return (regionNode.selector_ids || []).indexOf(changedSelectorId) !== -1;
    });
    if (!regionNodes.length) {
      return false;
    }
    regionNodes.forEach((regionNode) => {
      const wrapper = document.querySelector(
        '.export-region[data-leaf-page-id="' + leafPageId + '"][data-region-id="' + regionNode.region_id + '"]'
      );
      if (!wrapper) {
        return;
      }
      clearElement(wrapper);
      wrapper.appendChild(renderNode(resolveRegionContent(regionNode, leafPageId), leafPageId));
      plotManager.renderPendingPlots(wrapper);
    });
    plotManager.scheduleResize();
    return true;
  }
