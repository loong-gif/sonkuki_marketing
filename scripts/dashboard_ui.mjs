export const topN = (rows, limit) => [...rows].sort((left, right) => Number(right.value || 0) - Number(left.value || 0)).slice(0, limit);

export const shortPageLabel = (value) => {
  try {
    const url = new URL(value);
    const path = url.pathname.replace(/^\//, "").replace(/\/$/, "");
    return path ? `/${path.length > 34 ? `${path.slice(0, 33)}…` : path}` : "/";
  } catch {
    const text = String(value || "");
    return text.length > 35 ? `${text.slice(0, 34)}…` : text;
  }
};

export const productIdentity = ({ title, mpn }) => ({
  title: String(title || "Untitled product"),
  subtitle: String(mpn || "No MPN"),
});

export const coverageCopy = ({ status, checks }) => {
  if (status === "blocked") return { tone: "blocked", title: "数据快照已阻止 / Snapshot blocked", detail: "关键数据质量检查失败，公开指标已停止更新。" };
  const warnings = (checks || []).filter((check) => check.status === "warning").length;
  if (warnings) return { tone: "warning", title: "数据已加载，部分联表覆盖受限 / Data loaded with coverage caveats", detail: `${warnings} 项质量提示已保留在页面中；趋势与单渠道指标可正常使用。` };
  return { tone: "pass", title: "数据质量门禁通过 / Snapshot verified", detail: "统一指标口径、去重与公开快照隐私检查均已通过。" };
};

export const serializeFilters = (state) => {
  const params = new URLSearchParams();
  if (state.page && state.page !== "executive") params.set("page", state.page);
  for (const [key, value] of Object.entries({ from: state.from, to: state.to, brand: state.brand, pageType: state.pageType, query: state.query, product: state.product, competitorBrand: state.competitorBrand })) {
    if (value && value !== "all") params.set(key, value);
  }
  return params.toString();
};

export const parseFilters = (query) => {
  const params = new URLSearchParams(query);
  return {
    page: params.get("page") || "executive", from: params.get("from") || "", to: params.get("to") || "", brand: params.get("brand") || "all",
    pageType: params.get("pageType") || "all", query: params.get("query") || "", product: params.get("product") || "all", competitorBrand: params.get("competitorBrand") || "all",
  };
};
