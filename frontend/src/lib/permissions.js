// Pure permission check over the `/auth/me/` user shape — kept out of
// AuthContext so it unit-tests without React. The backend is the enforcement
// boundary; this only drives what the UI shows.
//
//   can(user, "orders.view_order")                  -> boolean
//   can(user, "auth.view_user", "auth.view_group")  -> AND over all perms
export function can(user, ...perms) {
  if (!user) return false;
  if (user.is_superuser) return true;
  const owned = user.permissions ?? [];
  return perms.every((p) => owned.includes(p));
}
