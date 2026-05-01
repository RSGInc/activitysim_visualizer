  function stateKey(currentState) {
    return currentState.weighting + "||" + currentState.values;
  }

  function findPageById(pageDescriptors, pageId) {
    return (pageDescriptors || []).find((page) => page.id === pageId) || null;
  }

  function hasChildren(pageDescriptor) {
    return !!(pageDescriptor && pageDescriptor.children && pageDescriptor.children.length);
  }

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

  function resolveActiveChildPageId(pageDescriptor) {
    const activeChildId = resolveActiveChildPageIdForState(pageDescriptor, state);
    if (!activeChildId) {
      fail(
        "Grouped export page " + pageDescriptor.id + " is missing child pages.",
        null,
        "MISSING_CHILD_PAGES"
      );
    }
    state.activeChildPage[pageDescriptor.id] = activeChildId;
    return activeChildId;
  }

  function currentLeafPageId(currentPayload, currentState) {
    if (!currentState.activePage) {
      return null;
    }
    const page = findPageById(currentPayload.pages || [], currentState.activePage);
    if (!page) {
      return null;
    }
    if (hasChildren(page)) {
      return resolveActiveChildPageIdForState(page, currentState);
    }
    return page.id;
  }

  function getInitialState(candidate) {
    const firstPage = candidate.pages.length ? candidate.pages[0] : null;
    const initialState = {
      weighting: candidate.default_state.weighting,
      values: candidate.default_state.values,
      activePage: firstPage ? firstPage.id : null,
      activeChildPage: {},
      pageSelectors: {},
    };

    function registerLeafPage(page) {
      const selectorState = {};
      (page.selectors || []).forEach((selector) => {
        if (selector.export_enabled) {
          selectorState[selector.id] = selector.default_value;
        }
      });
      initialState.pageSelectors[page.id] = selectorState;
    }

    (candidate.pages || []).forEach((page) => {
      if (hasChildren(page)) {
        const defaultChildId = resolveActiveChildPageIdForState(page, initialState);
        initialState.activeChildPage[page.id] = defaultChildId;
        (page.children || []).forEach(registerLeafPage);
        return;
      }
      registerLeafPage(page);
    });

    return initialState;
  }

  function updateSelectorState(currentState, pageId, selectorId, value) {
    const nextState = {
      weighting: currentState.weighting,
      values: currentState.values,
      activePage: currentState.activePage,
      activeChildPage: Object.assign({}, currentState.activeChildPage),
      pageSelectors: Object.assign({}, currentState.pageSelectors),
    };
    const pageState = Object.assign({}, nextState.pageSelectors[pageId] || {});
    pageState[selectorId] = value;
    nextState.pageSelectors[pageId] = pageState;
    return nextState;
  }
