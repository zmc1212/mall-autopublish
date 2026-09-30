import { useState } from "react";

/** 面板内分页的公共逻辑：页码钳制 + 当前页切片。 */
export function usePagination<T>(rows: T[], pageSize = 10) {
  const [rawPage, setPage] = useState(1);
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const page = Math.min(Math.max(rawPage, 1), pageCount);
  const pageRows = rows.slice((page - 1) * pageSize, page * pageSize);
  return { page, setPage, pageCount, pageRows, pageSize };
}
