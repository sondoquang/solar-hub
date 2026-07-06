import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client.js";

// Endpoints (Hub backend only):
//   GET    /auth/groups/      -> getGroups / useGroups (?page, ?page_size, ?search)
//   POST   /auth/groups/      -> createGroup / useCreateGroup ({name, permission_ids})
//   PATCH  /auth/groups/{id}/ -> updateGroup / useUpdateGroup
//   DELETE /auth/groups/{id}/ -> deleteGroup / useDeleteGroup (backend chặn khi nhóm còn người)
//   GET    /auth/permissions/ -> getPermissionCatalog / usePermissionCatalog
//     (ma trận quyền, nhãn tiếng Việt: [{module, label, models: [{model, label, permissions}]}])

const clean = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );

export const getGroups = (params = {}) =>
  api.get("/auth/groups/", { params: clean(params) }).then((r) => r.data);
export const createGroup = (payload) =>
  api.post("/auth/groups/", payload).then((r) => r.data);
export const updateGroup = ({ id, ...payload }) =>
  api.patch(`/auth/groups/${id}/`, payload).then((r) => r.data);
export const deleteGroup = (id) =>
  api.delete(`/auth/groups/${id}/`).then((r) => r.data);
export const getPermissionCatalog = () =>
  api.get("/auth/permissions/").then((r) => r.data);

const GROUPS_KEY = ["groups"];

export function useGroups(params = {}) {
  return useQuery({
    queryKey: [...GROUPS_KEY, "list", params],
    queryFn: () => getGroups(params),
  });
}

// The catalog only changes when the backend ships new models/permissions —
// cache it so re-opening the matrix modal doesn't refetch every time.
export function usePermissionCatalog({ enabled = true } = {}) {
  return useQuery({
    queryKey: ["permissions", "catalog"],
    queryFn: getPermissionCatalog,
    enabled,
    staleTime: 5 * 60_000,
  });
}

function useInvalidatingMutation(mutationFn) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: GROUPS_KEY });
      // User rows render group tags — keep them in sync with group renames.
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}

export const useCreateGroup = () => useInvalidatingMutation(createGroup);
export const useUpdateGroup = () => useInvalidatingMutation(updateGroup);
export const useDeleteGroup = () => useInvalidatingMutation(deleteGroup);
