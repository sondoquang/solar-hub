import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client.js";

// Per-site note history (Hub backend only). Multipart so a note carries its
// rich-text HTML plus image attachments in one request.
//   GET    /site-notes/?site=&page=&page_size=  -> getSiteNotes / useSiteNotes
//   POST   /site-notes/                         -> createSiteNote (FormData: site, content, images[])
//   PATCH  /site-notes/{id}/                     -> updateSiteNote (FormData: content, images[], remove_image_ids[])
//   DELETE /site-notes/{id}/                     -> deleteSiteNote (soft-delete)

const clean = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );

export const getSiteNotes = (siteId, params = {}) =>
  api.get("/site-notes/", { params: clean({ site: siteId, ...params }) }).then((r) => r.data);

export const createSiteNote = ({ siteId, content, images = [] }) => {
  const form = new FormData();
  form.append("site", siteId);
  form.append("content", content ?? "");
  images.forEach((file) => form.append("images", file));
  return api.post("/site-notes/", form).then((r) => r.data);
};

export const updateSiteNote = ({ id, content, images = [], removeImageIds = [] }) => {
  const form = new FormData();
  if (content != null) form.append("content", content);
  images.forEach((file) => form.append("images", file));
  removeImageIds.forEach((rid) => form.append("remove_image_ids", rid));
  return api.patch(`/site-notes/${id}/`, form).then((r) => r.data);
};

export const deleteSiteNote = (id) => api.delete(`/site-notes/${id}/`).then((r) => r.data);

// Query key carries the site id so each site's history caches independently.
const notesKey = (siteId) => ["site-notes", siteId];

export function useSiteNotes(siteId, params = {}) {
  return useQuery({
    queryKey: [...notesKey(siteId), params],
    queryFn: () => getSiteNotes(siteId, params),
    enabled: siteId != null,
    placeholderData: keepPreviousData,
  });
}

// Mutations invalidate the whole site's note history so the list refreshes.
function useNoteMutation(siteId, mutationFn) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => qc.invalidateQueries({ queryKey: notesKey(siteId) }),
  });
}

export const useCreateSiteNote = (siteId) => useNoteMutation(siteId, createSiteNote);
export const useUpdateSiteNote = (siteId) => useNoteMutation(siteId, updateSiteNote);
export const useDeleteSiteNote = (siteId) => useNoteMutation(siteId, deleteSiteNote);
