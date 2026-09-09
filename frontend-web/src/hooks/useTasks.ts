import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { TaskItem } from "../types";

/* 最近任务轮询（任务中心已并入案例库 Dashboard，4s 刷新） */
export function useTasks(pollMs = 4000) {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const list = await api.listTasks("all");
        if (alive) {
          setTasks(list);
          setLoading(false);
        }
      } catch {
        if (alive) setLoading(false);
      }
    };
    void load();
    const t = setInterval(load, pollMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [pollMs]);

  return { tasks, loading };
}
