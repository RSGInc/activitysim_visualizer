  /**
   * Region helpers and renderers.
   *
   * Regions are the runtime's selector-driven swap points. The JavaScript
   * lookup key must match the Python serializer exactly: selector values are
   * ordered by `node.selector_ids` and then serialized with JSON.stringify.
   */

  function buildRenderedRegionKey(leafPageId, regionId) {
    return String(leafPageId || "") + "::" + String(regionId || "");
  }

  function clearRenderedRegionRegistry(context) {
    context.renderedRegions = {};
  }

  function registerRenderedRegion(context, leafPageId, regionNode, wrapper) {
    const regionId = regionNode.region_id;
    if (!regionId) {
      fail(
        "Region nodes must include a region_id for runtime updates.",
        null,
        "MISSING_REGION_ID"
      );
    }
    const regionKey = buildRenderedRegionKey(leafPageId, regionId);
    if (context.renderedRegions[regionKey]) {
      fail(
        "Duplicate rendered region encountered for page " + leafPageId + " and region " + regionId + ".",
        null,
        "DUPLICATE_RENDERED_REGION"
      );
    }
    context.renderedRegions[regionKey] = wrapper;
  }

  function buildRegionVariantKey(selectorValues) {
    return JSON.stringify(selectorValues);
  }

  function getRegionSelectorValues(node, context, leafPageId) {
    const pageSelectorState = getPageSelectorState(context.state, leafPageId);
    return (node.selector_ids || []).map((selectorId) => {
      return pageSelectorState[selectorId];
    });
  }

  function resolveRegionContent(node, context, leafPageId) {
    const selectorValues = getRegionSelectorValues(node, context, leafPageId);
    const variantLookupKey = buildRegionVariantKey(selectorValues);
    if (node.variants && Object.prototype.hasOwnProperty.call(node.variants, variantLookupKey)) {
      return node.variants[variantLookupKey];
    }
    if (
      node.variant_aliases
      && Object.prototype.hasOwnProperty.call(node.variant_aliases, variantLookupKey)
      && node.variants
      && Object.prototype.hasOwnProperty.call(node.variants, node.variant_aliases[variantLookupKey])
    ) {
      return node.variants[node.variant_aliases[variantLookupKey]];
    }
    // Falling back to default_content is expected when Python intentionally
    // emitted a default snapshot for unmatched selector combinations. If that
    // was not intended, this usually indicates payload/schema drift.
    return node.default_content;
  }

  function renderRegion(node, context, actions, leafPageId) {
    const wrapper = el("div", {
      className: "export-region",
      attrs: {
        "data-region-id": node.region_id || "",
        "data-leaf-page-id": leafPageId || "",
        "data-selector-ids": JSON.stringify(node.selector_ids || []),
      },
    });
    registerRenderedRegion(context, leafPageId, node, wrapper);
    wrapper.appendChild(renderNode(resolveRegionContent(node, context, leafPageId), context, actions, leafPageId));
    return wrapper;
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
      for (const child of node.children || []) {
        collectRegionNodes(child, regions);
      }
      return regions;
    }
    if (node.kind === "tabs") {
      for (const tab of node.tabs || []) {
        collectRegionNodes(tab.content, regions);
      }
      return regions;
    }
    return regions;
  }

  function updateRenderedRegions(context, actions, leafPageId, changedSelectorId) {
    const pagesForState = getPagesForCurrentState(context.payload, context.state);
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
    for (const regionNode of regionNodes) {
      const wrapper = context.renderedRegions[
        buildRenderedRegionKey(leafPageId, regionNode.region_id)
      ];
      if (!wrapper) {
        return false;
      }
      clearElement(wrapper);
      wrapper.appendChild(
        renderNode(resolveRegionContent(regionNode, context, leafPageId), context, actions, leafPageId)
      );
      context.plotManager.renderPendingPlots(wrapper);
    }
    context.plotManager.scheduleResize();
    return true;
  }
