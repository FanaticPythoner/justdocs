const THEME_STORAGE_KEY = "justdocs-theme";
const NAV_SCROLL_STORAGE_PREFIX = "justdocs-nav-scroll";
const MERMAID_SOURCE_ATTR = "data-mermaid-source";
const SIDEBAR_KEY_PREFIX = "justdocs-sidebar";
const SIDEBAR_RESIZE_STEP = 16;
const JUSTDOCS_CONFIG = window.JUSTDOCS?.config || {};
const LAYOUT_CONFIG = JUSTDOCS_CONFIG.layout || {};
const SEARCH_CONFIG = JUSTDOCS_CONFIG.search || {};
const FEATURE_CONFIG = JUSTDOCS_CONFIG.features || {};
const PREFERENCES_ENABLED = JUSTDOCS_CONFIG.preferences?.enabled !== false;
const featureEnabled = (name) => FEATURE_CONFIG[name] !== false;
const FEATURES = {
    codeCopy: featureEnabled("codeCopy"),
    mermaid: featureEnabled("mermaid"),
    navigationScroll: featureEnabled("navigationScroll"),
    search: featureEnabled("search"),
    sidebars: featureEnabled("sidebars"),
    tableLabels: featureEnabled("tableLabels"),
    themeToggle: featureEnabled("themeToggle"),
};
const configuredInteger = (value, defaultValue, minimum = 0) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= minimum ? parsed : defaultValue;
};
const SEARCH_MIN_CHARS = configuredInteger(SEARCH_CONFIG.minChars, 2, 1);
const SEARCH_LIMIT = configuredInteger(SEARCH_CONFIG.limit, 8, 1);
const BREAKPOINTS = {
    compactTopbar: configuredInteger(LAYOUT_CONFIG.breakpoints?.compactTopbar, 980, 1),
    mobile: configuredInteger(LAYOUT_CONFIG.breakpoints?.mobile, 860, 1),
    rightDrawer: configuredInteger(LAYOUT_CONFIG.breakpoints?.rightDrawer, 1240, 1),
    small: configuredInteger(LAYOUT_CONFIG.breakpoints?.small, 520, 1),
};
const PREFERENCES = {
    contentWidth: {
        dataset: "justdocsContentWidth",
        key: "justdocs-content-width",
        values: ["narrow", "standard", "wide", "fluid"],
        defaultValue: LAYOUT_CONFIG.contentWidth || "standard",
    },
    density: {
        dataset: "justdocsDensity",
        key: "justdocs-density",
        values: ["comfortable", "compact"],
        defaultValue: LAYOUT_CONFIG.density || "comfortable",
    },
    motion: {
        dataset: "justdocsMotion",
        key: "justdocs-motion",
        values: ["system", "reduced"],
        defaultValue: LAYOUT_CONFIG.motion || "system",
    },
};

const normalizeText = (value) => value.replace(/\s+/g, " ").trim();

const configuredNumber = (value, defaultValue) => {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : defaultValue;
};

const sidebarConfig = (side) => {
    const source = LAYOUT_CONFIG.sidebars?.[side] || {};
    const defaults = side === "left"
        ? { defaultWidth: 296, max: 520, min: 220, ratio: 0.38 }
        : { defaultWidth: 260, max: 420, min: 200, ratio: 0.34 };
    return {
        collapseMargin: configuredNumber(source.collapseMargin, 56),
        cssVar: `--${side}-sidebar-width`,
        defaultWidth: configuredNumber(source.defaultWidth, defaults.defaultWidth),
        max: configuredNumber(source.max, defaults.max),
        min: configuredNumber(source.min, defaults.min),
        ratio: configuredNumber(source.viewportRatio, defaults.ratio),
        stateKey: `${SIDEBAR_KEY_PREFIX}-${side}-state`,
        widthKey: `${SIDEBAR_KEY_PREFIX}-${side}-width`,
    };
};

const SIDEBARS = {
    left: sidebarConfig("left"),
    right: sidebarConfig("right"),
};

const getBaseUrl = () => window.JUSTDOCS?.baseUrl || ".";

const resolveFromSiteRoot = (path) => {
    const root = new URL(`${getBaseUrl().replace(/\/?$/, "/")}`, location.href);
    return new URL(path, root).href;
};

const siteStorageKey = (suffix) => {
    const root = new URL(`${getBaseUrl().replace(/\/?$/, "/")}`, location.href);
    return `${suffix}:${root.origin}${root.pathname}`;
};

const applyTableLabels = () => {
    for (const table of document.querySelectorAll("table")) {
        const headers = Array.from(table.querySelectorAll("thead th")).map((cell) =>
            normalizeText(cell.textContent),
        );

        for (const row of table.querySelectorAll("tbody tr")) {
            Array.from(row.children).forEach((cell, index) => {
                const label = headers[index];
                if (label) {
                    cell.dataset.label = label;
                }
            });
        }
    }
};

const reportAsyncError = (error) => {
    setTimeout(() => {
        throw error;
    }, 0);
};

const setViewportState = () => {
    const width = window.innerWidth;
    const viewport = width <= BREAKPOINTS.mobile
            ? "mobile"
            : width <= BREAKPOINTS.rightDrawer ? "drawer" : "desktop";
    document.documentElement.dataset.justdocsViewport = viewport;
    document.documentElement.dataset.justdocsCompactTopbar =
        String(width <= BREAKPOINTS.compactTopbar);
    document.documentElement.dataset.justdocsSmall = String(width <= BREAKPOINTS.small);
    return viewport;
};

const syncTopbarHeight = () => {
    const topbar = document.querySelector(".topbar");
    if (!topbar) {
        return;
    }
    document.documentElement.style.setProperty(
        "--topbar-height",
        `${Math.ceil(topbar.getBoundingClientRect().height)}px`,
    );
};

const sidebarDatasetKey = (side) => `${side}Sidebar`;

const sidebarMaxForViewport = (config) =>
    Math.max(config.min, Math.min(config.max, Math.floor(window.innerWidth * config.ratio)));

const clampSidebarWidth = (side, width) => {
    const config = SIDEBARS[side];
    const max = sidebarMaxForViewport(config);
    return Math.min(Math.max(Math.round(width), config.min), max);
};

const readSidebarWidth = (side) => {
    const config = SIDEBARS[side];
    const parsed = Number.parseInt(localStorage.getItem(config.widthKey) || "", 10);
    return clampSidebarWidth(side, Number.isFinite(parsed) ? parsed : config.defaultWidth);
};

const sidebarIsCollapsed = (side) =>
    document.documentElement.dataset[sidebarDatasetKey(side)] === "collapsed";

const syncSidebarVisibility = (side, collapsed) => {
    const panel = document.getElementById(side === "left" ? "primary-navigation" : "page-sections");
    if (!panel) {
        return;
    }
    panel.toggleAttribute("inert", collapsed);
    panel.setAttribute("aria-hidden", String(collapsed));
};

const syncSidebarControls = (side) => {
    const config = SIDEBARS[side];
    const width = readSidebarWidth(side);
    const collapsed = sidebarIsCollapsed(side);

    for (const button of document.querySelectorAll(`[data-sidebar-toggle="${side}"]`)) {
        button.setAttribute("aria-pressed", String(collapsed));
    }

    for (const handle of document.querySelectorAll(`[data-sidebar-resizer="${side}"]`)) {
        handle.setAttribute("aria-disabled", String(collapsed));
        handle.setAttribute("aria-valuemin", String(config.min));
        handle.setAttribute("aria-valuemax", String(sidebarMaxForViewport(config)));
        handle.setAttribute("aria-valuenow", String(width));
    }

    syncSidebarVisibility(side, collapsed);
};

const applySidebarWidth = (side, width, persist = true) => {
    const config = SIDEBARS[side];
    const clamped = clampSidebarWidth(side, width);
    document.documentElement.style.setProperty(config.cssVar, `${clamped}px`);
    if (persist) {
        localStorage.setItem(config.widthKey, `${clamped}px`);
    }
    syncSidebarControls(side);
    return clamped;
};

const setSidebarCollapsed = (side, collapsed, persist = true) => {
    const config = SIDEBARS[side];
    document.documentElement.dataset[sidebarDatasetKey(side)] = collapsed ? "collapsed" : "expanded";
    if (persist) {
        localStorage.setItem(config.stateKey, collapsed ? "collapsed" : "expanded");
    }
    if (collapsed) {
        document.documentElement.style.setProperty(config.cssVar, "0px");
    } else {
        applySidebarWidth(side, readSidebarWidth(side), false);
    }
    syncSidebarControls(side);
};

const pointerSidebarWidth = (side, event) =>
    side === "left" ? event.clientX : window.innerWidth - event.clientX;

const defaultSidebarCollapsed = (side, storedState) =>
    side === "right" && !storedState && document.documentElement.dataset.justdocsViewport === "drawer";

const sidebarCollapseLimit = (side) => SIDEBARS[side].min - SIDEBARS[side].collapseMargin;

const sidebarExpandLimit = (side) => SIDEBARS[side].min + SIDEBARS[side].collapseMargin / 2;

const applyPointerSidebarWidth = (side, width) => {
    const collapsed = sidebarIsCollapsed(side);
    if (!collapsed && width < sidebarCollapseLimit(side)) {
        setSidebarCollapsed(side, true);
        return 0;
    }
    if (collapsed && width < sidebarExpandLimit(side)) {
        return 0;
    }
    if (collapsed) {
        setSidebarCollapsed(side, false);
    }
    return applySidebarWidth(side, width);
};

const initializeSidebarResizer = (side, handle) => {
    const stopResize = (event, moveHandler) => {
        handle.removeEventListener("pointermove", moveHandler);
        document.body.classList.remove("sidebar-resizing");
        if (handle.hasPointerCapture(event.pointerId)) {
            handle.releasePointerCapture(event.pointerId);
        }
    };

    handle.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) {
            return;
        }
        event.preventDefault();
        setSidebarCollapsed(side, false);
        handle.setPointerCapture(event.pointerId);
        document.body.classList.add("sidebar-resizing");

        const moveHandler = (moveEvent) => {
            applyPointerSidebarWidth(side, pointerSidebarWidth(side, moveEvent));
        };

        handle.addEventListener("pointermove", moveHandler);
        handle.addEventListener("pointerup", (upEvent) => stopResize(upEvent, moveHandler), {
            once: true,
        });
        handle.addEventListener("pointercancel", (cancelEvent) => stopResize(cancelEvent, moveHandler), {
            once: true,
        });
    });

    handle.addEventListener("keydown", (event) => {
        const sign = side === "left" ? 1 : -1;
        const width = readSidebarWidth(side);
        let nextWidth = null;

        if (event.key === "ArrowRight") {
            nextWidth = width + SIDEBAR_RESIZE_STEP * sign;
        } else if (event.key === "ArrowLeft") {
            nextWidth = width - SIDEBAR_RESIZE_STEP * sign;
        } else if (event.key === "Home") {
            nextWidth = SIDEBARS[side].min;
        } else if (event.key === "End") {
            nextWidth = sidebarMaxForViewport(SIDEBARS[side]);
        } else if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setSidebarCollapsed(side, !sidebarIsCollapsed(side));
            return;
        }

        if (nextWidth !== null) {
            event.preventDefault();
            setSidebarCollapsed(side, false);
            applySidebarWidth(side, nextWidth);
        }
    });
};

const initializeSidebars = () => {
    let currentViewport = setViewportState();

    for (const [side, config] of Object.entries(SIDEBARS)) {
        const storedState = localStorage.getItem(config.stateKey);
        const collapsed = storedState === "collapsed" || defaultSidebarCollapsed(side, storedState);
        document.documentElement.dataset[sidebarDatasetKey(side)] = collapsed ? "collapsed" : "expanded";
        if (collapsed) {
            document.documentElement.style.setProperty(config.cssVar, "0px");
        } else {
            applySidebarWidth(side, readSidebarWidth(side), false);
        }

        for (const button of document.querySelectorAll(`[data-sidebar-toggle="${side}"]`)) {
            button.addEventListener("click", () => {
                setSidebarCollapsed(side, !sidebarIsCollapsed(side));
            });
        }

        for (const button of document.querySelectorAll(`[data-sidebar-restore="${side}"]`)) {
            button.addEventListener("click", () => {
                setSidebarCollapsed(side, false);
            });
        }

        for (const button of document.querySelectorAll(`[data-sidebar-scrim="${side}"]`)) {
            button.addEventListener("click", () => {
                setSidebarCollapsed(side, true);
            });
        }

        for (const handle of document.querySelectorAll(`[data-sidebar-resizer="${side}"]`)) {
            initializeSidebarResizer(side, handle);
        }

        syncSidebarControls(side);
    }

    window.addEventListener("resize", () => {
        requestAnimationFrame(() => {
            const nextViewport = setViewportState();
            syncTopbarHeight();
            const storedRightState = localStorage.getItem(SIDEBARS.right.stateKey);
            if (nextViewport === "drawer" && currentViewport !== "drawer" && !storedRightState) {
                setSidebarCollapsed("right", true, false);
            } else if (nextViewport === "desktop" && currentViewport !== "desktop" && !storedRightState) {
                setSidebarCollapsed("right", false, false);
            }
            currentViewport = nextViewport;
            for (const side of Object.keys(SIDEBARS)) {
                if (!sidebarIsCollapsed(side)) {
                    applySidebarWidth(side, readSidebarWidth(side), false);
                }
                syncSidebarControls(side);
            }
        });
    });

    document.addEventListener("keydown", (event) => {
        if (
            event.key === "Escape" &&
            document.documentElement.dataset.justdocsViewport === "drawer" &&
            !sidebarIsCollapsed("right")
        ) {
            setSidebarCollapsed("right", true);
        }
    });
};

const preferenceValue = (name, useStored = true) => {
    const config = PREFERENCES[name];
    const stored = useStored ? localStorage.getItem(config.key) : null;
    if (config.values.includes(stored)) {
        return stored;
    }
    return config.values.includes(config.defaultValue) ? config.defaultValue : config.values[0];
};

const syncPreferenceControls = (name, value) => {
    for (const button of document.querySelectorAll(`[data-preference-choice="${name}"]`)) {
        button.setAttribute("aria-pressed", String(button.dataset.value === value));
    }
};

const setPreference = (name, value, persist = true) => {
    const config = PREFERENCES[name];
    if (!config || !config.values.includes(value)) {
        throw new Error(`invalid preference ${name}: ${value}`);
    }
    document.documentElement.dataset[config.dataset] = value;
    if (persist) {
        localStorage.setItem(config.key, value);
    }
    syncPreferenceControls(name, value);
};

const setPreferencesOpen = (toggle, panel, isOpen) => {
    panel.hidden = !isOpen;
    toggle.setAttribute("aria-expanded", String(isOpen));
};

const initializePreferences = () => {
    for (const name of Object.keys(PREFERENCES)) {
        setPreference(name, preferenceValue(name, PREFERENCES_ENABLED), false);
    }

    if (!PREFERENCES_ENABLED) {
        return;
    }

    const root = document.querySelector("[data-preferences]");
    if (!root) {
        return;
    }

    const toggle = root.querySelector("[data-preferences-toggle]");
    const panel = root.querySelector("[data-preferences-panel]");
    const reset = root.querySelector("[data-preferences-reset]");
    if (!toggle || !panel || !reset) {
        throw new Error("preferences controls missing");
    }

    toggle.addEventListener("click", () => {
        setPreferencesOpen(toggle, panel, panel.hidden);
    });

    for (const button of panel.querySelectorAll("[data-preference-choice]")) {
        button.addEventListener("click", () => {
            setPreference(button.dataset.preferenceChoice, button.dataset.value);
        });
    }

    reset.addEventListener("click", () => {
        for (const [name, config] of Object.entries(PREFERENCES)) {
            localStorage.removeItem(config.key);
            setPreference(name, preferenceValue(name), false);
        }
    });

    document.addEventListener("click", (event) => {
        if (!root.contains(event.target)) {
            setPreferencesOpen(toggle, panel, false);
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            setPreferencesOpen(toggle, panel, false);
        }
    });
};

const setSearchOpen = (input, panel, isOpen) => {
    panel.hidden = !isOpen;
    input.setAttribute("aria-expanded", String(isOpen));
};

const setSearchMessage = (status, results, message) => {
    status.hidden = false;
    status.textContent = message;
    results.replaceChildren();
};

const resultScore = (record, query) => {
    const title = record.title.toLowerCase();
    const text = record.text.toLowerCase();
    const location = record.location.toLowerCase();
    const titleIndex = title.indexOf(query);
    const textIndex = text.indexOf(query);
    const locationIndex = location.indexOf(query);
    let score = 0;

    if (titleIndex === 0) score += 100;
    if (titleIndex > 0) score += 70;
    if (locationIndex >= 0) score += 45;
    if (textIndex >= 0) score += 30;
    score -= Math.max(0, textIndex) / 400;

    return score;
};

const makeSnippet = (text, query) => {
    const normalized = normalizeText(text);
    const lower = normalized.toLowerCase();
    const index = lower.indexOf(query);
    if (index < 0) {
        return normalized.slice(0, 180);
    }
    const start = Math.max(0, index - 70);
    const end = Math.min(normalized.length, index + query.length + 110);
    return normalized.slice(start, end);
};

const appendHighlightedText = (parent, text, query) => {
    const lower = text.toLowerCase();
    let cursor = 0;
    let index = lower.indexOf(query, cursor);

    while (index >= 0) {
        if (index > cursor) {
            parent.append(document.createTextNode(text.slice(cursor, index)));
        }
        const mark = document.createElement("mark");
        mark.textContent = text.slice(index, index + query.length);
        parent.append(mark);
        cursor = index + query.length;
        index = lower.indexOf(query, cursor);
    }

    if (cursor < text.length) {
        parent.append(document.createTextNode(text.slice(cursor)));
    }
};

const renderResults = (status, results, matches, query) => {
    results.replaceChildren();
    status.hidden = matches.length > 0;
    status.textContent = matches.length > 0 ? "" : "No results";

    for (const match of matches.slice(0, SEARCH_LIMIT)) {
        const item = document.createElement("li");
        const link = document.createElement("a");
        const title = document.createElement("strong");
        const snippet = document.createElement("span");

        link.href = resolveFromSiteRoot(match.location);
        title.textContent = match.title;
        appendHighlightedText(snippet, match.snippet, query);
        link.append(title, snippet);
        item.append(link);
        results.append(item);
    }
};

const buildSearchIndex = async () => {
    const response = await fetch(resolveFromSiteRoot("search/search_index.json"));
    if (!response.ok) {
        throw new Error(`search index fetch failed: ${response.status}`);
    }
    const payload = await response.json();
    if (!Array.isArray(payload.docs)) {
        throw new Error("search index malformed: docs missing");
    }
    return payload.docs.map((record) => ({
        location: String(record.location || ""),
        title: normalizeText(String(record.title || record.location || "")),
        text: normalizeText(String(record.text || "")),
    }));
};

const searchRecords = (records, rawQuery) => {
    const query = rawQuery.trim().toLowerCase();
    if (query.length < SEARCH_MIN_CHARS) {
        return [];
    }

    return records
        .map((record) => ({
            ...record,
            score: resultScore(record, query),
            snippet: makeSnippet(record.text, query),
        }))
        .filter((record) => record.score > 0)
        .sort((left, right) => right.score - left.score || left.location.localeCompare(right.location));
};

const initializeSearch = () => {
    const root = document.querySelector("[data-search]");
    const input = document.querySelector("[data-search-input]");
    const panel = document.querySelector("[data-search-panel]");
    const status = document.querySelector("[data-search-status]");
    const results = document.querySelector("[data-search-results]");
    let indexPromise;

    if (!root || !input || !panel || !status || !results) {
        throw new Error("search controls missing");
    }

    const runSearch = async () => {
        const query = input.value.trim().toLowerCase();
        setSearchOpen(input, panel, true);
        if (query.length < SEARCH_MIN_CHARS) {
            setSearchMessage(status, results, `Enter ${SEARCH_MIN_CHARS}+ characters`);
            return;
        }
        status.hidden = false;
        status.textContent = "Indexing docs";
        indexPromise ||= buildSearchIndex();
        const records = await indexPromise;
        renderResults(status, results, searchRecords(records, query), query);
    };

    input.addEventListener("focus", () => {
        setSearchOpen(input, panel, true);
        if (!input.value.trim()) {
            setSearchMessage(status, results, `Enter ${SEARCH_MIN_CHARS}+ characters`);
        }
    });

    input.addEventListener("input", () => {
        runSearch().catch((error) => {
            setSearchMessage(status, results, error instanceof Error ? error.message : String(error));
        });
    });

    input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            input.value = "";
            setSearchOpen(input, panel, false);
        }
    });

    document.addEventListener("keydown", (event) => {
        const active = document.activeElement;
        const isTyping = active && ["INPUT", "TEXTAREA", "SELECT"].includes(active.tagName);
        if (event.key === "/" && !isTyping && !event.metaKey && !event.ctrlKey && !event.altKey) {
            event.preventDefault();
            input.focus();
        }
    });

    document.addEventListener("click", (event) => {
        if (!root.contains(event.target)) {
            setSearchOpen(input, panel, false);
        }
    });
};

const initializeNavigationScrollState = () => {
    const nav = document.querySelector("nav.left");
    if (!nav) {
        return;
    }

    const key = siteStorageKey(NAV_SCROLL_STORAGE_PREFIX);
    const rawPosition = sessionStorage.getItem(key);
    const savedPosition = rawPosition === null ? null : Number.parseInt(rawPosition, 10);

    const maxScroll = () => Math.max(0, nav.scrollHeight - nav.clientHeight);

    const setScrollTop = (position) => {
        nav.scrollTop = Math.min(Math.max(0, Math.round(position)), maxScroll());
    };

    const savePosition = () => {
        sessionStorage.setItem(key, String(Math.max(0, Math.round(nav.scrollTop))));
    };

    const keepActiveVisible = (center = false) => {
        const active = nav.querySelector("a.active");
        if (!active) {
            return;
        }
        const navRect = nav.getBoundingClientRect();
        const activeRect = active.getBoundingClientRect();
        const margin = 16;
        if (nav.clientHeight <= 0 || activeRect.height <= 0) {
            return;
        }
        const relativeTop = activeRect.top - navRect.top + nav.scrollTop;
        if (activeRect.top < navRect.top + margin) {
            setScrollTop(relativeTop - margin);
        } else if (activeRect.bottom > navRect.bottom - margin) {
            setScrollTop(relativeTop + activeRect.height - nav.clientHeight + margin);
        } else if (center) {
            setScrollTop(relativeTop - (nav.clientHeight - activeRect.height) / 2);
        }
    };

    requestAnimationFrame(() => {
        if (Number.isFinite(savedPosition)) {
            setScrollTop(savedPosition);
            keepActiveVisible();
            return;
        }

        keepActiveVisible(true);
    });

    nav.addEventListener("scroll", savePosition, { passive: true });
    nav.addEventListener("click", (event) => {
        if (event.target.closest("a[href]")) {
            savePosition();
        }
    });
    window.addEventListener("resize", () => requestAnimationFrame(() => keepActiveVisible()));
    window.addEventListener("pagehide", savePosition);
};

const setTheme = (theme) => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_STORAGE_KEY, theme);
};

const mermaidTheme = () => (document.documentElement.dataset.theme === "dark" ? "dark" : "default");

const prepareMermaidBlocks = () => {
    const prepared = [];
    for (const code of document.querySelectorAll("pre > code.language-mermaid, pre > code.mermaid")) {
        const pre = code.parentElement;
        if (!pre) {
            continue;
        }
        pre.className = "mermaid";
        pre.textContent = code.textContent;
        prepared.push(pre);
    }

    for (const node of document.querySelectorAll(".mermaid")) {
        if (!node.hasAttribute(MERMAID_SOURCE_ATTR)) {
            node.setAttribute(MERMAID_SOURCE_ATTR, node.textContent.trim());
        }
        prepared.push(node);
    }

    return Array.from(new Set(prepared)).filter((node) => node.textContent.trim());
};

const renderMermaidBlocks = async () => {
    const diagrams = prepareMermaidBlocks();
    if (diagrams.length === 0) {
        return;
    }
    if (!window.mermaid) {
        throw new Error("mermaid asset missing");
    }

    window.mermaid.initialize({
        securityLevel: "strict",
        startOnLoad: false,
        theme: mermaidTheme(),
    });

    for (const diagram of diagrams) {
        diagram.removeAttribute("data-processed");
        diagram.textContent = diagram.getAttribute(MERMAID_SOURCE_ATTR);
    }
    await window.mermaid.run({ nodes: diagrams });
};

const initializeMermaid = () => {
    if (!FEATURES.mermaid) {
        return;
    }
    renderMermaidBlocks().catch(reportAsyncError);
};

const initializeThemeToggle = () => {
    if (!FEATURES.themeToggle) {
        return;
    }

    const button = document.querySelector("[data-theme-toggle]");
    const label = document.querySelector("[data-theme-toggle-label]");

    if (!button || !label) {
        throw new Error("theme toggle missing");
    }

    const sync = () => {
        const isDark = document.documentElement.dataset.theme === "dark";
        button.setAttribute("aria-pressed", String(isDark));
        label.textContent = isDark ? "Light" : "Dark";
    };

    button.addEventListener("click", () => {
        const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
        setTheme(current === "dark" ? "light" : "dark");
        sync();
        renderMermaidBlocks().catch(reportAsyncError);
    });

    sync();
};

const initializeCodeBlocks = () => {
    if (!window.hljs) {
        throw new Error("highlight assets missing");
    }
    if (FEATURES.codeCopy) {
        if (!window.CopyButtonPlugin) {
            throw new Error("copy button asset missing");
        }
        window.hljs.addPlugin(new window.CopyButtonPlugin({ autohide: false }));
    }
    window.hljs.highlightAll();
};

const initializeTheme = () => {
    syncTopbarHeight();
    if (FEATURES.sidebars) {
        initializeSidebars();
    } else {
        setViewportState();
    }
    window.addEventListener("resize", () => requestAnimationFrame(syncTopbarHeight));
    initializePreferences();
    initializeMermaid();
    initializeCodeBlocks();
    if (FEATURES.tableLabels) {
        applyTableLabels();
    }
    if (FEATURES.navigationScroll) {
        initializeNavigationScrollState();
    }
    initializeThemeToggle();
    if (FEATURES.search) {
        initializeSearch();
    }
};

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeTheme, { once: true });
} else {
    initializeTheme();
}
