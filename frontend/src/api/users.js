import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client.js";

// Endpoints (Hub backend only):
//   GET    /auth/users/                   -> getUsers / useUsers (?page, ?page_size, ?ordering, ?search, ?is_active, ?group)
//   POST   /auth/users/                   -> createUser / useCreateUser ({username, password, email, full_name, group_ids})
//   PATCH  /auth/users/{id}/              -> updateUser / useUpdateUser ({email, full_name, group_ids, is_active})
//   DELETE /auth/users/{id}/              -> deactivateUser / useDeactivateUser (vô hiệu hóa — backend không xóa row)
//   POST   /auth/users/{id}/activate/     -> activateUser / useActivateUser
//   POST   /auth/users/{id}/set_password/ -> setUserPassword / useSetUserPassword (admin đặt lại mật khẩu)

// Drop empty params so the URL only carries meaningful query keys.
const clean = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );

export const getUsers = (params = {}) =>
  api.get("/auth/users/", { params: clean(params) }).then((r) => r.data);
export const createUser = (payload) =>
  api.post("/auth/users/", payload).then((r) => r.data);
export const updateUser = ({ id, ...payload }) =>
  api.patch(`/auth/users/${id}/`, payload).then((r) => r.data);
export const deactivateUser = (id) =>
  api.delete(`/auth/users/${id}/`).then((r) => r.data);
export const activateUser = (id) =>
  api.post(`/auth/users/${id}/activate/`).then((r) => r.data);
export const setUserPassword = ({ id, password }) =>
  api.post(`/auth/users/${id}/set_password/`, { password }).then((r) => r.data);

const USERS_KEY = ["users"];

export function useUsers(params = {}) {
  return useQuery({
    queryKey: [...USERS_KEY, "list", params],
    queryFn: () => getUsers(params),
    placeholderData: keepPreviousData,
  });
}

function useInvalidatingMutation(mutationFn) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export const useCreateUser = () => useInvalidatingMutation(createUser);
export const useUpdateUser = () => useInvalidatingMutation(updateUser);
export const useDeactivateUser = () => useInvalidatingMutation(deactivateUser);
export const useActivateUser = () => useInvalidatingMutation(activateUser);
export const useSetUserPassword = () => useInvalidatingMutation(setUserPassword);
