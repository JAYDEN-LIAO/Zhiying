import { useState, useCallback, useRef } from "react";
import { api } from "../services/api";
import type { SearchResultItem, FaceSearchResult } from "../types";

interface SearchState {
  query: string;
  results: SearchResultItem[];
  searching: boolean;
  hasSearched: boolean;
  error: string | null;
}

interface FaceSearchState {
  searching: boolean;
  results: FaceSearchResult[];
}

/**
 * Manages semantic search and face search state.
 */
export function useSearch() {
  const [state, setState] = useState<SearchState>({
    query: "",
    results: [],
    searching: false,
    hasSearched: false,
    error: null,
  });
  const [face, setFace] = useState<FaceSearchState>({
    searching: false,
    results: [],
  });
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const searchSemantic = useCallback(async (query: string, videoIds?: string[]) => {
    if (!query.trim()) return;
    setState((prev) => ({ ...prev, query, searching: true, error: null, hasSearched: true }));
    try {
      const data = await api.searchSemantic(query, { video_ids: videoIds });
      setState((prev) => ({ ...prev, results: data.results ?? [], searching: false }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        searching: false,
        error: err instanceof Error ? err.message : "搜索失败",
      }));
    }
  }, []);

  const searchFace = useCallback(async (file: File, videoIds?: string[]) => {
    setFace({ searching: true, results: [] });
    try {
      const results = await api.searchFace(file, videoIds);
      setFace({ searching: false, results });
    } catch {
      setFace({ searching: false, results: [] });
    }
  }, []);

  const clear = useCallback(() => {
    setState({ query: "", results: [], searching: false, hasSearched: false, error: null });
    setFace({ searching: false, results: [] });
  }, []);

  return {
    ...state,
    faceResults: face.results,
    faceSearching: face.searching,
    fileInputRef,
    searchSemantic,
    searchFace,
    clear,
  };
}
