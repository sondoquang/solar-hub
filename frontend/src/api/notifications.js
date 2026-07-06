import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "./client.js";

// Persistent push-run notifications (Hub backend) — back the app-wide "đã push
// xong" modal + the push notification bell:
//   GET  /notifications/               -> getNotifications (paginated; the envelope
//        also carries { unread, running } counts). Finalizes RUNNING rows on read.
//   POST /notifications/{id}/read/     -> markNotificationRead (clear one)
//   POST /notifications/mark_all_read/ -> markAllNotificationsRead (clear the badge)

export const getNotifications = () =>
  api.get("/notifications/").then((r) => r.data);

export const markNotificationRead = (id) =>
  api.post(`/notifications/${id}/read/`).then((r) => r.data);

export const markAllNotificationsRead = () =>
  api.post("/notifications/mark_all_read/").then((r) => r.data);

const KEY = ["notifications"];

// Lazy fetch (no interval polling): a push run is now reported by email, so the
// bell only needs fresh data when the app (re)mounts or a mutation invalidates
// this key (e.g. right after triggering a push — see notifyStarted). The backend
// still finalizes RUNNING rows on read, and the Celery beat sweep is the primary
// finalizer, so completion no longer depends on the frontend polling. ``staleTime``
// keeps quick remounts from refetching.
export function useNotifications({ enabled = true } = {}) {
  return useQuery({
    queryKey: [...KEY, "list"],
    queryFn: getNotifications,
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
