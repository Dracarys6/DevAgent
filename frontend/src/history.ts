import { useCallback, useState } from "react";

export interface LocalHistoryEntry<TInput, TReport> {
  id: string;
  title?: string;
  created_at: string;
  input: TInput;
  report: TReport;
}

export interface LocalHistoryStore<TInput, TReport> {
  entries: LocalHistoryEntry<TInput, TReport>[];
  add: (entry: LocalHistoryEntry<TInput, TReport>) => void;
  clear: () => void;
}

const MAX_HISTORY_ENTRIES = 10;

function loadHistory<TInput, TReport>(key: string): LocalHistoryEntry<TInput, TReport>[] {
  try {
    const value = window.localStorage.getItem(key);
    if (!value) return [];
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed)
      ? (parsed as LocalHistoryEntry<TInput, TReport>[]).slice(0, MAX_HISTORY_ENTRIES)
      : [];
  } catch {
    // ! 损坏或不可访问的浏览器缓存不能阻断核心 API 功能。
    return [];
  }
}

export function useLocalHistory<TInput, TReport>(
  key: string,
): LocalHistoryStore<TInput, TReport> {
  const [entries, setEntries] = useState<LocalHistoryEntry<TInput, TReport>[]>(
    () => loadHistory<TInput, TReport>(key),
  );

  const add = useCallback((entry: LocalHistoryEntry<TInput, TReport>) => {
    setEntries((current) => {
      const next = [entry, ...current.filter((item) => item.id !== entry.id)].slice(
        0,
        MAX_HISTORY_ENTRIES,
      );
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // ! 配额不足时仍保留当前页面会话内的历史，不影响报告展示。
      }
      return next;
    });
  }, [key]);

  const clear = useCallback(() => {
    setEntries([]);
    try {
      window.localStorage.removeItem(key);
    } catch {
      // ! 存储不可访问时，至少清理当前页面会话中的历史。
    }
  }, [key]);

  return { entries, add, clear };
}
