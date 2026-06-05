import { api } from "./client.js";

export async function loginUser({ username, password }) {
  const { data } = await api.post("/auth/token/", { username, password });
  return data; // { access, refresh }
}

export async function refreshAccessToken(refresh) {
  const { data } = await api.post("/auth/token/refresh/", { refresh });
  return data; // { access, refresh? }
}

export async function getMe() {
  const { data } = await api.get("/auth/me/");
  return data; // { id, username, email, full_name, role }
}

export async function updateProfile(payload) {
  const { data } = await api.patch("/auth/me/", payload);
  return data; // updated { id, username, email, full_name, role }
}

export async function changePassword({ old_password, new_password }) {
  await api.post("/auth/change-password/", { old_password, new_password });
}
