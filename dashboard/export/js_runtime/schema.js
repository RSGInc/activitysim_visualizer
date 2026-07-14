  /**
   * Payload parsing and validation helpers.
   *
   * The runtime still trusts Python to build the payload, but we validate the
   * most important cross-field references here so contract drift fails fast
   * with targeted runtime errors instead of confusing partial renders.
   */

  function parsePayload() {
    if (!dataElement) {
      fail("Export payload script element was not found.", null, "PAYLOAD_ELEMENT_MISSING");
    }
    try {
      return JSON.parse(dataElement.textContent || "");
    } catch (error) {
      fail(
        "Export payload JSON could not be parsed.",
        error && error.message ? error.message : error,
        "PAYLOAD_PARSE_FAILED"
      );
    }
  }

  function collectLeafPages(pageDescriptors, leafPages) {
    for (const pageDescriptor of pageDescriptors || []) {
      if (hasChildren(pageDescriptor)) {
        collectLeafPages(pageDescriptor.children || [], leafPages);
      } else {
        leafPages.push(pageDescriptor);
      }
    }
    return leafPages;
  }

  function collectPageDescriptors(pageDescriptors, allPages) {
    for (const pageDescriptor of pageDescriptors || []) {
      allPages.push(pageDescriptor);
      if (hasChildren(pageDescriptor)) {
        collectPageDescriptors(pageDescriptor.children || [], allPages);
      }
    }
    return allPages;
  }

  function collectRegionsForValidation(node, regions) {
    if (!node || typeof node !== "object") {
      return regions;
    }
    if (node.kind === "region") {
      regions.push(node);
      collectRegionsForValidation(node.default_content, regions);
      for (const variantNode of Object.values(node.variants || {})) {
        collectRegionsForValidation(variantNode, regions);
      }
      return regions;
    }
    if (node.kind === "container" || node.kind === "card") {
      for (const child of node.children || []) {
        collectRegionsForValidation(child, regions);
      }
      return regions;
    }
    if (node.kind === "tabs") {
      for (const tab of node.tabs || []) {
        collectRegionsForValidation(tab.content, regions);
      }
    }
    return regions;
  }

  function validateUniquePageIds(candidate) {
    const pages = collectPageDescriptors(candidate.pages || [], []);
    const seenPageIds = {};
    for (const pageDescriptor of pages) {
      if (seenPageIds[pageDescriptor.id]) {
        fail(
          "Export payload contains duplicate page id " + pageDescriptor.id + ".",
          null,
          "DUPLICATE_PAGE_ID"
        );
      }
      seenPageIds[pageDescriptor.id] = true;
    }
  }

  function validateDefaultState(candidate) {
    const stateKey = buildDashboardStateKey(candidate.default_state);
    if (!candidate.states[stateKey]) {
      fail(
        "Export payload is missing state data for its default dashboard state " + stateKey + ".",
        null,
        "MISSING_DEFAULT_STATE_ENTRY"
      );
    }
    if (
      (candidate.dashboard_controls.weighting || []).indexOf(candidate.default_state.weighting) === -1
      || (candidate.dashboard_controls.values || []).indexOf(candidate.default_state.values) === -1
    ) {
      fail(
        "Export payload default dashboard state does not match the available dashboard controls.",
        null,
        "INVALID_DEFAULT_DASHBOARD_STATE"
      );
    }
  }

  function validatePageDescriptors(candidate) {
    for (const pageDescriptor of collectPageDescriptors(candidate.pages || [], [])) {
      if (hasChildren(pageDescriptor)) {
        const childIds = (pageDescriptor.children || []).map((childPage) => childPage.id);
        if (!pageDescriptor.default_page_id || childIds.indexOf(pageDescriptor.default_page_id) === -1) {
          fail(
            "Grouped export page " + pageDescriptor.id + " has an invalid default_page_id.",
            null,
            "INVALID_DEFAULT_PAGE_REFERENCE"
          );
        }
      }
      for (const selector of pageDescriptor.selectors || []) {
        if (
          selector.default_value !== undefined
          && selector.default_value !== null
          && (selector.options || []).indexOf(selector.default_value) === -1
        ) {
          fail(
            "Selector " + selector.id + " on page " + pageDescriptor.id + " has a default_value that is not in options.",
            null,
            "INVALID_SELECTOR_DEFAULT"
          );
        }
        if (selector.parent_selector_id) {
          const parentSelector = (pageDescriptor.selectors || []).find((candidate) => {
            return candidate.id === selector.parent_selector_id;
          });
          if (!parentSelector) {
            fail(
              "Selector " + selector.id + " on page " + pageDescriptor.id + " references an unknown parent selector.",
              null,
              "INVALID_SELECTOR_PARENT"
            );
          }
          for (const options of Object.values(selector.options_by_parent_value || {})) {
            for (const option of options || []) {
              if ((selector.options || []).indexOf(option) === -1) {
                fail(
                  "Dependent selector " + selector.id + " contains an option outside its exported domain.",
                  null,
                  "INVALID_DEPENDENT_SELECTOR_OPTION"
                );
              }
            }
          }
        }
      }
    }
  }

  function validateStates(candidate) {
    const leafPages = collectLeafPages(candidate.pages || [], []);
    const leafPageIds = {};
    for (const leafPage of leafPages) {
      leafPageIds[leafPage.id] = leafPage;
    }

    for (const [stateId, pagesForState] of Object.entries(candidate.states || {})) {
      for (const leafPage of leafPages) {
        const pageNode = pagesForState[leafPage.id];
        if (!pageNode) {
          fail(
            "State " + stateId + " is missing page content for leaf page " + leafPage.id + ".",
            null,
            "MISSING_STATE_PAGE"
          );
        }
        if (!pageNode || pageNode.kind !== "page") {
          fail(
            "State " + stateId + " contains invalid page content for leaf page " + leafPage.id + ".",
            null,
            "INVALID_STATE_PAGE"
          );
        }
        const selectorIds = {};
        for (const selector of leafPage.selectors || []) {
          selectorIds[selector.id] = true;
        }
        const seenRegionIds = {};
        for (const regionNode of collectRegionsForValidation(pageNode.content, [])) {
          if (!regionNode.region_id) {
            fail(
              "Leaf page " + leafPage.id + " contains a region without region_id.",
              null,
              "MISSING_REGION_ID"
            );
          }
          if (seenRegionIds[regionNode.region_id]) {
            fail(
              "Leaf page " + leafPage.id + " contains duplicate region id " + regionNode.region_id + ".",
              null,
              "DUPLICATE_REGION_ID"
            );
          }
          seenRegionIds[regionNode.region_id] = true;
          for (const selectorId of regionNode.selector_ids || []) {
            if (!selectorIds[selectorId]) {
              fail(
                "Region " + regionNode.region_id + " on page " + leafPage.id + " references unknown selector " + selectorId + ".",
                null,
                "UNKNOWN_REGION_SELECTOR"
              );
            }
          }
        }
      }

      for (const pageId of Object.keys(pagesForState || {})) {
        if (!leafPageIds[pageId]) {
          fail(
            "State " + stateId + " references unknown page id " + pageId + ".",
            null,
            "UNKNOWN_STATE_PAGE"
          );
        }
      }
    }
  }

  function validatePayloadSchema(candidate) {
    if (!candidate || typeof candidate !== "object") {
      fail("Export payload was missing or malformed.", null, "INVALID_PAYLOAD");
    }
    if (candidate.schema_version !== SUPPORTED_SCHEMA_VERSION) {
      fail(
        "Unsupported export schema version. Expected "
          + SUPPORTED_SCHEMA_VERSION
          + " but received "
          + String(candidate.schema_version || "<missing>")
          + ".",
        null,
        "SCHEMA_VERSION_UNSUPPORTED"
      );
    }
    if (!Array.isArray(candidate.pages)) {
      fail("Export payload is missing its page descriptors.", null, "MISSING_PAGE_DESCRIPTORS");
    }
    if (!candidate.default_state || typeof candidate.default_state !== "object") {
      fail("Export payload is missing its default dashboard state.", null, "MISSING_DEFAULT_STATE");
    }
    if (!candidate.states || typeof candidate.states !== "object") {
      fail("Export payload is missing required dashboard state data.", null, "MISSING_STATE_DATA");
    }
    if (!candidate.dashboard_controls || typeof candidate.dashboard_controls !== "object") {
      fail("Export payload is missing dashboard controls metadata.", null, "MISSING_DASHBOARD_CONTROLS");
    }
    validateUniquePageIds(candidate);
    validateDefaultState(candidate);
    validatePageDescriptors(candidate);
    validateStates(candidate);
  }
