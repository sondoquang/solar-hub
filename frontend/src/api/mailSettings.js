import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client.js";

// System-wide SMTP config (singleton on the backend):
//   GET   /mail-settings/       -> getMailSettings / useMailSettings
//   PATCH /mail-settings/       -> updateMailSettings / useUpdateMailSettings
//       body: { smtp_host, smtp_port, use_tls, use_ssl, username, from_email,
//               from_name, recipients: string[], digest_enabled,
//               digest_times: string[] ("HH:MM"), password? }
//       `password` is write-only; omit/blank to keep the stored one.
//       `digest_times` are the daily auto-send slots (local time, normalized
//       server-side to zero-padded, deduped, sorted "HH:MM").
//   POST  /mail-settings/test/  -> sendTestMail / useSendTestMail
//       body: { recipients: string[] } — sends a verification email through the
//       saved config to every address listed.

const KEY = ["mail-settings"];

export const getMailSettings = () => api.get("/mail-settings/").then((r) => r.data);

export const updateMailSettings = (payload) =>
  api.patch("/mail-settings/", payload).then((r) => r.data);

// Accepts a single address or a list; sends a verification email to all of them.
export const sendTestMail = (recipients) =>
  api
    .post("/mail-settings/test/", {
      recipients: Array.isArray(recipients) ? recipients : [recipients],
    })
    .then((r) => r.data);

export function useMailSettings() {
  return useQuery({ queryKey: KEY, queryFn: getMailSettings });
}

// On success the server returns the fresh settings; seed the cache so the form
// re-renders with the saved values (and the updated `has_password` flag).
export function useUpdateMailSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: updateMailSettings,
    onSuccess: (data) => qc.setQueryData(KEY, data),
  });
}

export function useSendTestMail() {
  return useMutation({ mutationFn: sendTestMail });
}
