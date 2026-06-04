import { useQuery } from "@tanstack/react-query";

import { api } from "./client.js";

// GET /api/health/ → { status, db, redis }
export const getHealth = () => api.get("/health/").then((r) => r.data);

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: getHealth });
