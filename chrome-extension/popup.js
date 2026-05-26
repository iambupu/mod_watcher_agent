const DEFAULT_BACKEND_URL = "http://127.0.0.1:17500";
const STORAGE_KEYS = ["backendUrl", "accessToken"];
const STORAGE_AREA = chrome.storage.local;

const backendInput = document.getElementById("backend-url");
const gameNameInput = document.getElementById("game-name");
const adultContentInput = document.getElementById("adult-content");
const tokenInput = document.getElementById("access-token");
const noteInput = document.getElementById("user-note");
const saveButton = document.getElementById("save-button");
const messageEl = document.getElementById("message");
const pageStatusEl = document.getElementById("page-status");
const previewEl = document.getElementById("mod-preview");
const sourceEl = document.getElementById("mod-source");
const titleEl = document.getElementById("mod-title");
const metaEl = document.getElementById("mod-meta");

let capturedMod = null;

function setMessage(text, type = "") {
  messageEl.textContent = text;
  messageEl.className = `message ${type}`.trim();
}

function extractPageMod() {
  const GENERIC_LOVERSLAB_LABELS = new Set([
    "activity",
    "account",
    "all activity",
    "browse",
    "home",
    "search",
    "staff",
    "store",
    "support",
    "unread content",
    "downloads",
    "files",
    "file",
    "forums",
    "loverslab",
    "other",
  ]);

  function normalizeText(value) {
    const text = (value || "").replace(/\s+/g, " ").trim();
    if (!text || !/[&<]/.test(text)) return text;
    const element = document.createElement("textarea");
    element.innerHTML = text;
    return element.value.replace(/\s+/g, " ").trim();
  }

  function textFromPageSelector(...selectors) {
    for (const selector of selectors) {
      const element = document.querySelector(selector);
      const text = normalizeText(element?.textContent);
      if (text) return text;
    }
    return "";
  }

  function pageMetaContent(...selectors) {
    for (const selector of selectors) {
      const value = normalizeText(document.querySelector(selector)?.getAttribute("content"));
      if (value) return value;
    }
    return "";
  }

  function firstJsonLdValue(extractor) {
    for (const script of document.querySelectorAll("script[type='application/ld+json']")) {
      let data;
      try {
        data = JSON.parse(script.textContent || "{}");
      } catch {
        continue;
      }
      const nodes = Array.isArray(data) ? data : [data];
      for (const node of nodes) {
        const value = extractor(node);
        if (value) return value;
      }
    }
    return "";
  }

  function imageUrlFromJsonLdValue(value) {
    if (!value) return "";
    if (typeof value === "string") return value;
    if (Array.isArray(value)) {
      for (const item of value) {
        const url = imageUrlFromJsonLdValue(item);
        if (url) return url;
      }
      return "";
    }
    return value.url || value.contentUrl || "";
  }

  function extractNexusThumbnailUrl() {
    return pageMetaContent("meta[property='og:image']", "meta[name='twitter:image']");
  }

  function extractLoversLabThumbnailUrl() {
    const fullUrlElement = document.querySelector("[data-fullurl*='static.loverslab.com/screenshots/']");
    const fullUrl = fullUrlElement?.getAttribute("data-fullurl")?.trim();
    if (fullUrl) return fullUrl;

    const jsonLdImage = firstJsonLdValue((node) =>
      imageUrlFromJsonLdValue(node.screenshot || node.image || node.thumbnailUrl),
    );
    if (jsonLdImage) return normalizeText(jsonLdImage);

    return pageMetaContent("meta[property='og:image']", "meta[name='twitter:image']");
  }

  function cleanPageTitle(value) {
    return normalizeText(value)
      .replace(/\s+-\s+Nexus mods.*$/i, "")
      .replace(/\s+-\s+LoversLab.*$/i, "")
      .trim();
  }

  function extractLoversLabTaxonomy(modTitle) {
    function taxonomyFromJsonLdBreadcrumbs(modTitle) {
      for (const script of document.querySelectorAll("script[type='application/ld+json']")) {
        let data;
        try {
          data = JSON.parse(script.textContent || "{}");
        } catch {
          continue;
        }
        const nodes = Array.isArray(data) ? data : [data];
        for (const node of nodes) {
          if (node?.["@type"] !== "BreadcrumbList" || !Array.isArray(node.itemListElement)) continue;
          const labels = node.itemListElement
            .slice()
            .sort((a, b) => Number(a.position || 0) - Number(b.position || 0))
            .map((entry) => normalizeText(entry?.item?.name || entry?.name))
            .filter(Boolean);
          const filtered = labels.filter((label) => {
            const normalized = label.toLowerCase();
            if (GENERIC_LOVERSLAB_LABELS.has(normalized)) return false;
            if (modTitle && normalized === modTitle.toLowerCase()) return false;
            return true;
          });
          return {
            labels,
            game: filtered[0] || "",
            category: filtered.length > 1 ? filtered[filtered.length - 1] : null,
          };
        }
      }
      return null;
    }

    function contextFromIpsDataLayer() {
      const scripts = Array.from(document.scripts);
      for (const script of scripts) {
        const text = script.textContent || "";
        const match = text.match(/const\s+IpsDataLayerContext\s*=\s*(\{.*?\});/s);
        if (!match) continue;
        try {
          const context = JSON.parse(match[1]);
          return {
            categoryLabel: normalizeText(context.content_container_name),
            categoryUrl: normalizeText(context.content_container_url),
          };
        } catch {
          return {};
        }
      }
      return {};
    }

    function collectLabels(selectors) {
      const labels = [];
      for (const selector of selectors) {
        for (const element of document.querySelectorAll(selector)) {
          const label = normalizeText(element.textContent);
          if (!label || labels.includes(label)) continue;
          labels.push(label);
        }
      }
      return labels;
    }

    function findParentGameFromCategoryMenu(categoryUrl, categoryLabel) {
      if (!categoryUrl && !categoryLabel) return "";
      for (const link of document.querySelectorAll("a[href*='/files/category/']")) {
        const href = link.href || link.getAttribute("href") || "";
        const label = normalizeText(link.textContent);
        const urlMatches = categoryUrl && href.replace(/\/+$/, "") === categoryUrl.replace(/\/+$/, "");
        const labelMatches = categoryLabel && label.toLowerCase() === categoryLabel.toLowerCase();
        if (!urlMatches && !labelMatches) continue;

        const parent = link.closest(".ipsDrawer_itemParent");
        const parentLabel = normalizeText(parent?.querySelector(".ipsDrawer_title a, h4 a, h4")?.textContent);
        if (parentLabel && !GENERIC_LOVERSLAB_LABELS.has(parentLabel.toLowerCase())) {
          return parentLabel;
        }
      }
      return "";
    }

    const breadcrumbSelectors = [
      "nav[aria-label*='breadcrumb' i] a",
      ".ipsBreadcrumb a",
      "ul.ipsBreadcrumb a",
      "[data-role='breadcrumb'] a",
      "ol.breadcrumb a",
      ".breadcrumb a",
    ];
    const jsonLdTaxonomy = taxonomyFromJsonLdBreadcrumbs(modTitle);
    if (jsonLdTaxonomy) {
      return {
        game: jsonLdTaxonomy.game,
        category: jsonLdTaxonomy.category,
      };
    }

    const breadcrumbLabels = collectLabels(breadcrumbSelectors);
    const dataLayerContext = contextFromIpsDataLayer();
    const labels = breadcrumbLabels.length
      ? breadcrumbLabels
      : (dataLayerContext.categoryLabel ? [dataLayerContext.categoryLabel] : []);
    const filtered = labels.filter((label) => {
      const normalized = label.toLowerCase();
      if (GENERIC_LOVERSLAB_LABELS.has(normalized)) return false;
      if (modTitle && normalized === modTitle.toLowerCase()) return false;
      return true;
    });

    const category = filtered.length ? filtered[filtered.length - 1] : null;
    const game = filtered.length > 1
      ? filtered[filtered.length - 2]
      : findParentGameFromCategoryMenu(dataLayerContext.categoryUrl, category);
    return { game, category };
  }

  function extractNexusModsPage(url) {
    const match = url.pathname.match(/^\/([^/]+)\/mods\/(\d+)/i);
    if (!match) {
      return { error: "当前不是 Nexus Mods 的 mod 详情页。" };
    }
    const title =
      cleanPageTitle(
        textFromPageSelector("h1", "[data-e2e='mod-title']") ||
          pageMetaContent("meta[property='og:title']", "meta[name='twitter:title']") ||
          document.title,
      ) || "Untitled mod";
    const author =
      textFromPageSelector("[data-e2e='mod-author']", ".modtabs .author a") ||
      pageMetaContent("meta[name='author']");
    return {
      source: "nexusmods",
      external_id: match[2],
      game: match[1],
      game_domain: match[1],
      title,
      url: url.toString(),
      author: author || null,
      adult_content: false,
      original_summary: pageMetaContent("meta[name='description']", "meta[property='og:description']") || null,
      thumbnail_url: extractNexusThumbnailUrl() || null,
      raw_json: JSON.stringify({
        captured_from: "chrome-extension",
        captured_at: new Date().toISOString(),
        page_title: document.title,
      }),
    };
  }

  function extractLoversLabPage(url) {
    const match = url.pathname.match(/^\/files\/file\/(\d+)(?:-|\/|$)/i);
    if (!match) {
      return { error: "当前不是 LoversLab 的文件详情页。" };
    }
    const title =
      cleanPageTitle(
        textFromPageSelector("h1.ipsType_pageTitle", ".ipsType_pageTitle", "[data-role='fileTitle']") ||
          pageMetaContent("meta[property='og:title']", "meta[name='twitter:title']") ||
          document.title,
      ) || "Untitled mod";
    const taxonomy = extractLoversLabTaxonomy(title);
    const author =
      textFromPageSelector(
        "a[href*='/profile/']",
        ".ipsType_reset a[href*='user']",
        "a[rel='author']",
      ) || pageMetaContent("meta[name='author']", "meta[property='article:author']");
    return {
      source: "loverslab",
      external_id: match[1],
      game: taxonomy.game,
      game_domain: null,
      title,
      url: url.toString(),
      author: author || null,
      category: taxonomy.category,
      adult_content: true,
      original_summary: pageMetaContent("meta[name='description']", "meta[property='og:description']") || null,
      thumbnail_url: extractLoversLabThumbnailUrl() || null,
      raw_json: JSON.stringify({
        captured_from: "chrome-extension",
        captured_at: new Date().toISOString(),
        page_title: document.title,
        breadcrumbs: taxonomy.game ? undefined : "not_detected",
      }),
    };
  }

  const url = new URL(window.location.href);
  const hostname = url.hostname.replace(/^www\./, "").toLowerCase();
  if (hostname === "nexusmods.com") {
    return extractNexusModsPage(url);
  }
  if (hostname === "loverslab.com") {
    return extractLoversLabPage(url);
  }
  return { error: "只支持 Nexus Mods 和 LoversLab 页面。" };
}

function normalizeBackendUrl(value) {
  const raw = (value || DEFAULT_BACKEND_URL).trim().replace(/\/+$/, "");
  if (raw.endsWith("/api")) return raw.slice(0, -4);
  return raw;
}

function buildImportUrl(baseUrl) {
  return `${normalizeBackendUrl(baseUrl)}/api/favorites/import`;
}

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0];
}

async function captureCurrentPage() {
  const tab = await getActiveTab();
  if (!tab?.id) {
    throw new Error("无法读取当前标签页。");
  }
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: extractPageMod,
  });
  return result?.result;
}

function renderCapturedMod(mod) {
  if (!mod || mod.error) {
    capturedMod = null;
    previewEl.hidden = true;
    gameNameInput.value = "";
    adultContentInput.checked = false;
    pageStatusEl.textContent = mod?.error || "未识别当前页面。";
    saveButton.disabled = true;
    return;
  }
  capturedMod = mod;
  sourceEl.textContent = mod.source === "nexusmods" ? "Nexus Mods" : "LoversLab";
  titleEl.textContent = mod.title;
  metaEl.textContent = `${mod.game || mod.source} #${mod.external_id}`;
  gameNameInput.value = mod.game || "";
  adultContentInput.checked = mod.adult_content === true;
  previewEl.hidden = false;
  pageStatusEl.textContent = "已识别当前 Mod 页面。";
  saveButton.disabled = false;
}

async function loadSettings() {
  const stored = await STORAGE_AREA.get(STORAGE_KEYS);
  backendInput.value = stored.backendUrl || DEFAULT_BACKEND_URL;
  tokenInput.value = stored.accessToken || "";
}

async function saveSettings() {
  await STORAGE_AREA.set({
    backendUrl: normalizeBackendUrl(backendInput.value),
    accessToken: tokenInput.value.trim(),
  });
}

async function saveFavorite() {
  if (!capturedMod) return;
  saveButton.disabled = true;
  setMessage("正在写入 Mod Watcher...");
  try {
    await saveSettings();
    const headers = { "Content-Type": "application/json" };
    const token = tokenInput.value.trim();
    if (token) {
      headers["X-Mod-Watcher-Token"] = token;
    }
    const response = await fetch(buildImportUrl(backendInput.value), {
      method: "POST",
      headers,
      credentials: "include",
      body: JSON.stringify({
        ...capturedMod,
        game: gameNameInput.value.trim(),
        adult_content: adultContentInput.checked,
        user_note: noteInput.value.trim() || null,
        user_tags_json: JSON.stringify(["chrome"]),
      }),
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        detail = body.detail || body.message || detail;
      } catch {
        // Keep the HTTP status text when the backend does not return JSON.
      }
      throw new Error(`API ${response.status}: ${detail}`);
    }
    setMessage("已保存并收藏。", "success");
  } catch (error) {
    setMessage(error instanceof Error ? error.message : "保存失败。", "error");
  } finally {
    saveButton.disabled = false;
  }
}

saveButton.addEventListener("click", saveFavorite);

loadSettings()
  .then(captureCurrentPage)
  .then(renderCapturedMod)
  .catch((error) => {
    renderCapturedMod({ error: error instanceof Error ? error.message : "读取页面失败。" });
  });
