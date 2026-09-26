"use strict";
(async function () {
  const files = {ja: "/static/locales/ja.json", en: "/static/locales/en.json"};
  const resources = {};
  try {
    for (const [language, url] of Object.entries(files)) {
      const response = await fetch(url, {cache: "no-cache"});
      if (!response.ok) throw new Error(`Could not load ${url}`);
      resources[language] = await response.json();
    }
  } catch (error) {
    console.error("Translation resources could not be loaded", error);
    return;
  }

  const originalText = new WeakMap();
  const originalAttributes = new WeakMap();
  const translatedText = new WeakMap();
  const textNodes = new Set();
  const elements = new Set();
  let language = localStorage.getItem("yue2-language") === "en" ? "en" : "ja";
  const translate = (value, depth = 0) => {
    const text = String(value);
    if (language === "en" && depth < 3 && text.includes("\n")) {
      return text.split("\n").map((line) => translate(line, depth + 1)).join("\n");
    }
    const exact = resources[language].strings[text] ?? resources[language].messages?.[text];
    if (exact !== undefined) return exact;
    for (const pattern of resources[language].patterns || []) {
      const expression = new RegExp(pattern.source);
      const match = text.match(expression);
      if (match) return text.replace(expression, () => pattern.target.replace(/\$(\d+|&)/g, (token, index) => {
        if (index === "&") return match[0];
        const part = match[Number(index)] ?? token;
        return translate(part, depth + 1);
      }));
    }
    return text;
  };
  const textAttributes = ["placeholder", "title", "aria-label", "aria-description"];
  function translateAttributes(node) {
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    elements.add(node);
    let saved = originalAttributes.get(node);
    if (!saved) { saved = new Map(); originalAttributes.set(node, saved); }
    for (const name of textAttributes) {
      if (!node.hasAttribute(name)) continue;
      if (!saved.has(name)) saved.set(name, node.getAttribute(name));
      const output = translate(saved.get(name));
      if (node.getAttribute(name) !== output) {
        node.setAttribute(name, output);
      }
    }
    if (node instanceof HTMLInputElement && ["button", "submit", "reset"].includes(node.type)) {
      if (!saved.has("value")) saved.set("value", node.value);
      node.value = translate(saved.get("value"));
    }
  }
  function translateText(node) {
    if (node.nodeType !== Node.TEXT_NODE) return;
    if (!originalText.has(node)) originalText.set(node, node.nodeValue);
    else if (node.nodeValue !== translatedText.get(node)) originalText.set(node, node.nodeValue);
    textNodes.add(node);
    const source = originalText.get(node);
    const trimmed = source.trim();
    if (!trimmed) return;
    const translated = translate(trimmed);
    const lead = source.match(/^\s*/)?.[0] || "";
    const trail = source.match(/\s*$/)?.[0] || "";
    const output = `${lead}${translated}${trail}`;
    translatedText.set(node, output);
    if (node.nodeValue !== output) node.nodeValue = output;
  }
  function apply(root = document) {
    if (root.nodeType === Node.TEXT_NODE) { translateText(root); return; }
    if (root.nodeType === Node.ELEMENT_NODE) translateAttributes(root);
    if (root.querySelectorAll) for (const node of root.querySelectorAll("*")) translateAttributes(node);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) translateText(node);
  }
  function translateTracked() {
    for (const node of textNodes) {
      if (!node.isConnected) { textNodes.delete(node); continue; }
      translateText(node);
    }
    for (const node of elements) {
      if (!node.isConnected) { elements.delete(node); continue; }
      translateAttributes(node);
    }
    document.documentElement.lang = language;
    const button = document.getElementById("language-toggle");
    if (button) {
      button.textContent = language === "ja" ? "EN" : "日本語";
      button.title = translate("言語を切り替え");
      button.setAttribute("aria-label", translate("言語を切り替え"));
    }
  }
  const localizeTree = (value) => {
    if (typeof value === "string") return translate(value);
    if (Array.isArray(value)) return value.map(localizeTree);
    if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, localizeTree(item)]));
    return value;
  };
  window.I18n = {get language() { return language; }, t: translate, apply, localizeTree};
  const nativeAlert = window.alert.bind(window), nativeConfirm = window.confirm.bind(window);
  window.alert = (message) => nativeAlert(translate(message));
  window.confirm = (message) => nativeConfirm(translate(message));
  const initialize = () => {
    apply();
    document.documentElement.lang = language;
    document.getElementById("language-toggle")?.addEventListener("click", () => {
      language = language === "ja" ? "en" : "ja";
      localStorage.setItem("yue2-language", language);
      translateTracked();
      window.dispatchEvent(new CustomEvent("yue2-language-changed", {detail: {language}}));
    });
    let pending = new Set();
    let scheduled = false;
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        if (record.type === "characterData") {
          translateText(record.target);
          continue;
        }
        for (const node of record.addedNodes) if (node.nodeType === Node.ELEMENT_NODE || node.nodeType === Node.TEXT_NODE) pending.add(node);
      }
      if (scheduled || pending.size === 0) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        const roots = [...pending]; pending = new Set();
        const topRoots = roots.filter((node) => !roots.some((other) => other !== node && other.nodeType === Node.ELEMENT_NODE && other.contains(node)));
        for (const root of topRoots) apply(root);
        document.documentElement.lang = language;
      });
    });
    observer.observe(document.body, {subtree: true, childList: true, characterData: true});
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, {once: true});
  else initialize();
})();
