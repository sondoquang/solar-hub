import { useQuery } from "@tanstack/react-query";

import { api } from "./client.js";

export function useDashboard(params) {
  return useQuery({
    queryKey: ["dashboard", params],
    queryFn: () => api.get("/dashboard/", { params }).then((r) => r.data),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}
