export function pageSlice<T>(items: T[], requestedPage: number, pageSize = 100) {
  const size = Number.isFinite(pageSize) ? Math.max(1, Math.floor(pageSize)) : 100;
  const pages = Math.max(1, Math.ceil(items.length / size));
  const page = Number.isFinite(requestedPage) ? Math.max(1, Math.min(pages, Math.floor(requestedPage))) : 1;
  return { page, pages, items: items.slice((page - 1) * size, page * size) };
}
