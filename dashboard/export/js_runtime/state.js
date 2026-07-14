  /**
   * State helpers for the export runtime.
   *
   * These helpers are intentionally pure where possible so the runtime reads
   * more like Python data transformation code than browser-oriented state
   * mutation.
   */

  function buildDashboardStateKey(currentState) {
    return currentState.weighting + "||" + currentState.values;
  }

  function findPageById(pageDescriptors, pageId) {
    for (const page of pageDescriptors || []) {
      if (page.id === pageId) {
        return page;
      }
    }
    return null;
  }

  function findPageDescriptorById(pageDescriptors, pageId) {
    for (const page of pageDescriptors || []) {
      if (page.id === pageId) {
        return page;
      }
      const childMatch = findPageDescriptorById(page.children || [], pageId);
      if (childMatch) {
        return childMatch;
      }
    }
    return null;
  }

  function hasChildren(pageDescriptor) {
    return !!(pageDescriptor && pageDescriptor.children && pageDescriptor.children.length);
  }

  /**
   * Resolve the leaf child page for a grouped page without mutating state.
   */
  function resolveActiveChildPageIdForState(pageDescriptor, currentState) {
    const childIds = (pageDescriptor.children || []).map((childPage) => childPage.id);
    if (!childIds.length) {
      return null;
    }

    const preferredChildId = currentState.activeChildPage[pageDescriptor.id];
    if (preferredChildId && childIds.indexOf(preferredChildId) !== -1) {
      return preferredChildId;
    }
    if (
      pageDescriptor.default_page_id
      && childIds.indexOf(pageDescriptor.default_page_id) !== -1
    ) {
      return pageDescriptor.default_page_id;
    }
    return childIds[0];
  }

  function getActivePageDescriptor(currentPayload, currentState) {
    if (!currentState.activePage) {
      return null;
    }
    return findPageById(currentPayload.pages || [], currentState.activePage);
  }

  function getLeafPageId(currentPayload, currentState) {
    const pageDescriptor = getActivePageDescriptor(currentPayload, currentState);
    if (!pageDescriptor) {
      return null;
    }
    if (hasChildren(pageDescriptor)) {
      return resolveActiveChildPageIdForState(pageDescriptor, currentState);
    }
    return pageDescriptor.id;
  }

  function getPagesForCurrentState(currentPayload, currentState) {
    return currentPayload.states[buildDashboardStateKey(currentState)] || null;
  }

  function getPageSelectorState(currentState, leafPageId) {
    return currentState.pageSelectors[leafPageId] || {};
  }

  function cloneState(currentState) {
    return {
      weighting: currentState.weighting,
      values: currentState.values,
      activePage: currentState.activePage,
      activeChildPage: Object.assign({}, currentState.activeChildPage),
      pageSelectors: Object.assign({}, currentState.pageSelectors),
    };
  }

  function registerLeafPageSelectorDefaults(initialState, pageDescriptor) {
    const selectorState = {};
    for (const selector of pageDescriptor.selectors || []) {
      if (selector.export_enabled) {
        selectorState[selector.id] = selector.default_value;
      }
    }
    initialState.pageSelectors[pageDescriptor.id] = selectorState;
  }

  /**
   * Normalize state in one explicit place.
   *
   * This is where default page/child-page fallbacks are applied so "read"
   * helpers elsewhere can remain side-effect free.
   */
  function normalizeState(currentPayload, currentState) {
    const nextState = cloneState(currentState);
    const rootPages = currentPayload.pages || [];
    if (!nextState.activePage) {
      nextState.activePage = rootPages.length ? rootPages[0].id : null;
    }

    for (const pageDescriptor of rootPages) {
      if (hasChildren(pageDescriptor)) {
        const activeChildId = resolveActiveChildPageIdForState(pageDescriptor, nextState);
        if (!activeChildId) {
          fail(
            "Grouped export page " + pageDescriptor.id + " is missing child pages.",
            null,
            "MISSING_CHILD_PAGES"
          );
        }
        nextState.activeChildPage[pageDescriptor.id] = activeChildId;
      }
    }
    return nextState;
  }

  function getInitialState(candidate) {
    const initialState = {
      weighting: candidate.default_state.weighting,
      values: candidate.default_state.values,
      activePage: candidate.pages.length ? candidate.pages[0].id : null,
      activeChildPage: {},
      pageSelectors: {},
    };

    for (const pageDescriptor of candidate.pages || []) {
      if (hasChildren(pageDescriptor)) {
        for (const childPage of pageDescriptor.children || []) {
          registerLeafPageSelectorDefaults(initialState, childPage);
        }
      } else {
        registerLeafPageSelectorDefaults(initialState, pageDescriptor);
      }
    }

    return normalizeState(candidate, initialState);
  }

  function updateDashboardControlState(currentPayload, currentState, controlKey, value) {
    const nextState = cloneState(currentState);
    nextState[controlKey] = value;
    return normalizeState(currentPayload, nextState);
  }

  function setActivePageInState(currentPayload, currentState, pageId) {
    const nextState = cloneState(currentState);
    nextState.activePage = pageId;
    return normalizeState(currentPayload, nextState);
  }

  function setActiveChildPageInState(currentPayload, currentState, pageId, childPageId) {
    const nextState = cloneState(currentState);
    nextState.activeChildPage[pageId] = childPageId;
    return normalizeState(currentPayload, nextState);
  }

  function updateSelectorState(currentPayload, currentState, pageId, selectorId, value) {
    const nextState = cloneState(currentState);
    const pageState = Object.assign({}, nextState.pageSelectors[pageId] || {});
    pageState[selectorId] = value;
    if (
      pageId === "vmt"
      && selectorId === "personal_auto_vmt_breakdown"
      && value !== "Home Geography"
    ) {
      pageState.personal_auto_vmt_geography_type = "All Geography Types";
    }
    if (
      pageId === "vmt"
      && selectorId === "non_motorized_vmt_breakdown"
      && value !== "Home Geography"
    ) {
      pageState.non_motorized_vmt_geography_type = "All Geography Types";
    }
    const pageDescriptor = findPageDescriptorById(currentPayload.pages || [], pageId);
    for (const selector of (pageDescriptor && pageDescriptor.selectors) || []) {
      if (selector.parent_selector_id !== selectorId) {
        continue;
      }
      const dependentOptions = (
        selector.options_by_parent_value
        && selector.options_by_parent_value[value]
      ) || [];
      if (dependentOptions.length) {
        pageState[selector.id] = dependentOptions[0];
      }
    }
    nextState.pageSelectors[pageId] = pageState;
    return normalizeState(currentPayload, nextState);
  }
