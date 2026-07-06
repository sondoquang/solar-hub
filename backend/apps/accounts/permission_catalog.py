"""Curated permission catalog — single source of truth for RBAC-assignable
permissions and their Vietnamese labels.

Only the models listed in ``MODULES`` are exposed to the group matrix UI
(``GET /api/auth/permissions/``) and accepted by ``GroupSerializer``; internal
models (mappings, logs, ``admin.logentry``…) never leak into group config.
Per model, a prefix whitelist trims meaningless boxes (read-only resources
don't offer add/delete); custom ``Meta.permissions`` codenames are always
included and carry their own already-Vietnamese ``Permission.name``.
"""

from django.contrib.auth.models import Permission
from django.db.models import Q

ACTION_LABELS = {"view": "Xem", "add": "Thêm", "change": "Sửa", "delete": "Xóa"}
ACTION_ORDER = ("view", "add", "change", "delete")

# (module key, module VN label, [(app_label, model, model VN label,
#   allowed standard prefixes or None = all four)])
MODULES = [
    ("orders", "Đơn hàng", [
        ("orders", "order", "Đơn hàng", None),
    ]),
    ("catalog", "Sản phẩm", [
        ("catalog", "masterproduct", "Sản phẩm", None),
        ("catalog", "category", "Danh mục", None),
    ]),
    ("sites", "Website", [
        ("sites", "site", "Website", None),
        ("sites", "hosting", "Hosting", None),
        ("sites", "sitenote", "Ghi chú website", None),
    ]),
    ("domains", "Tên miền", [
        ("domains", "domaininfo", "Thông tin tên miền", ("view",)),
    ]),
    ("monitoring", "Giám sát", [
        ("monitoring", "healthcheck", "Lịch sử kiểm tra", ("view",)),
    ]),
    ("sync", "Báo cáo đồng bộ", [
        ("sync", "synclog", "Báo cáo đồng bộ", ("view",)),
    ]),
    ("mailer", "Email", [
        ("mailer", "mailsettings", "Cấu hình mail", ("view", "change")),
    ]),
    ("accounts", "Người dùng & phân quyền", [
        ("auth", "user", "Người dùng", None),
        ("auth", "group", "Nhóm quyền", None),
    ]),
]


def _model_q():
    q = Q()
    for _, _, models in MODULES:
        for app_label, model, _, _ in models:
            q |= Q(content_type__app_label=app_label, content_type__model=model)
    return q


def _disallowed_q():
    q = Q()
    for _, _, models in MODULES:
        for app_label, model, _, prefixes in models:
            if prefixes is None:
                continue
            banned = [f"{a}_{model}" for a in ACTION_ORDER if a not in prefixes]
            if banned:
                q |= Q(
                    content_type__app_label=app_label,
                    content_type__model=model,
                    codename__in=banned,
                )
    return q


def curated_permissions_qs():
    """Lazy queryset of every assignable permission (backs both the catalog
    endpoint and ``GroupSerializer.permission_ids`` validation)."""
    return Permission.objects.filter(_model_q()).exclude(_disallowed_q())


def build_catalog():
    """Grouped catalog for the FE matrix: module → model → permissions."""
    by_model = {}
    for perm in curated_permissions_qs().select_related("content_type"):
        key = (perm.content_type.app_label, perm.content_type.model)
        by_model.setdefault(key, []).append(perm)

    catalog = []
    for module, module_label, models in MODULES:
        model_entries = []
        for app_label, model, model_label, _ in models:
            standard = {f"{a}_{model}": a for a in ACTION_ORDER}

            def sort_key(perm):
                action = standard.get(perm.codename)
                order = ACTION_ORDER.index(action) if action else len(ACTION_ORDER)
                return (order, perm.codename)

            entries = []
            for perm in sorted(by_model.get((app_label, model), []), key=sort_key):
                action = standard.get(perm.codename)
                entries.append({
                    "id": perm.id,
                    "codename": perm.codename,
                    "perm": f"{app_label}.{perm.codename}",
                    "label": ACTION_LABELS[action] if action else perm.name,
                    "is_custom": action is None,
                })
            model_entries.append(
                {"model": model, "label": model_label, "permissions": entries}
            )
        catalog.append(
            {"module": module, "label": module_label, "models": model_entries}
        )
    return catalog
