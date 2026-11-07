/* 牧鱼 · 路由兼容层 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ManagerIA = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const LEGACY_ROUTES = {
    market: "capMarket",
    plugins: "capInstalled",
    biliConsole: "capBili",
    douyinConsole: "capDouyin",
    dsh: "capDshPlugins",
    dshSkills: "capDshSkills",
    dshAccess: "capDshAccess",
    guard: "capGuard",
    groupGuard: "capGuard",
  };

  const KNOWN_ROUTES = new Set([
    "overview",
    "hubBots",
    "hubLive",
    "hubGroup",
    "hubPersona",
    "hubMemory",
    "hubAuto",
    "hubPlugin",
    "hubMonitor",
    "bots",
    "inbox",
    "life",
    "people",
    "memes",
    "vision",
    "capMarket",
    "capInstalled",
    "capGuard",
    "capOwner",
    "capMatrix",
    "capDshPlugins",
    "capDshSkills",
    "capDshAccess",
    "capBili",
    "capDouyin",
    "approvals",
    "automationCenter",
    "tasks",
    "digest",
    "duet",
    "memory",
    "memoryFix",
    "models",
    "personaRelease",
    "learn",
    "mood",
    "human",
    "presenceLoops",
    "presenceRelations",
    "presenceRhythm",
    "presenceRadar",
    "presenceDiary",
    "evals",
    "review",
    "think",
    "logs",
    "alerts",
    "drift",
    "resources",
    "canary",
    "settings",
  ]);

  function routeKey(value) {
    const text = String(value || "").replace(/^#\/?/, "");
    return text.split("?")[0] || "overview";
  }

  function resolveRoute(value) {
    const key = routeKey(value);
    const legacy = LEGACY_ROUTES[key];
    if (legacy) return { route: legacy, redirect: true };
    if (KNOWN_ROUTES.has(key)) return { route: key, redirect: false };
    return { route: "overview", redirect: key !== "overview" };
  }

  return {
    LEGACY_ROUTES,
    KNOWN_ROUTES,
    routeKey,
    resolveRoute,
  };
});
