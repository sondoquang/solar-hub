"""Project-wide RBAC permission layer (installed as the DRF default).

Resolution order per request:

1. ViewSet ``action_perms = {"forward": ["orders.forward_order"]}`` — wins
   for the current ``@action`` when listed.
2. View ``required_perms = {"POST": ["mailer.test_mailsettings"]}`` — per
   HTTP method, for APIViews / plain ViewSets without a queryset.
3. Model map via the view's queryset (``add/change/delete_<model>`` plus
   ``view_<model>`` on GET/HEAD, which stock DjangoModelPermissions skips).
4. No queryset resolvable → authenticated-only fall-through (keeps ``/me/``,
   ``/dashboard/``, notifications working). Deliberately permissive: every
   NEW queryset-less view must declare ``required_perms`` itself (see
   PROJECT_RULE).

Superusers pass every check automatically (``ModelBackend.has_perm``).
"""

from rest_framework.permissions import DjangoModelPermissions


class RBACPermission(DjangoModelPermissions):
    perms_map = {
        **DjangoModelPermissions.perms_map,
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
    }

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        action = getattr(view, "action", None)
        action_perms = getattr(view, "action_perms", {})
        if action and action in action_perms:
            return user.has_perms(action_perms[action])

        required = getattr(view, "required_perms", {})
        if request.method in required:
            return user.has_perms(required[request.method])

        queryset = self._queryset_or_none(view)
        if queryset is None:
            return True
        return user.has_perms(
            self.get_required_permissions(request.method, queryset.model)
        )

    @staticmethod
    def _queryset_or_none(view):
        # Unlike DjangoModelPermissions._queryset, never assert — generic
        # views without a queryset (e.g. APIView) must fall through, not 500.
        try:
            if callable(getattr(view, "get_queryset", None)):
                return view.get_queryset()
        except (AssertionError, AttributeError):
            pass
        return getattr(view, "queryset", None)
