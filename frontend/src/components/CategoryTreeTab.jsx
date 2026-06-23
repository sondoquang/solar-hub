import { Empty, Input, Table, Tree } from "antd";
import { FolderTree, Layers, Network, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import {
  useCategoryOverview,
  useCategorySiteLinks,
  useProductCategories,
} from "../api/products.js";
import { formatDate } from "../lib/format.js";
import EmptyState from "./EmptyState.jsx";
import ErrorState from "./ErrorState.jsx";
import StatCards from "./StatCards.jsx";
import StatusDot from "./StatusDot.jsx";

const vi = (n) => (n ?? 0).toLocaleString("vi-VN");
const byName = (a, b) => a.name.localeCompare(b.name, "vi");

// Build the parent→children index + a memoised descendant-count for each node
// (the number shown on a tree row = size of its subtree, NOT product counts —
// the catalog stores categories by name, so per-category product counts would
// be expensive; this stays cheap and fully client-side off the flat list).
function buildTree(categories) {
  const byId = new Map();
  const byParent = new Map();
  for (const c of categories) {
    byId.set(c.id, c);
    const key = c.parent ?? "root";
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key).push(c);
  }
  const descCount = new Map();
  const countDesc = (id) => {
    if (descCount.has(id)) return descCount.get(id);
    const children = byParent.get(id) ?? [];
    let total = children.length;
    for (const ch of children) total += countDesc(ch.id);
    descCount.set(id, total);
    return total;
  };
  const make = (c) => ({
    key: c.id,
    title: c.name,
    children: (byParent.get(c.id) ?? []).sort(byName).map(make),
  });
  const roots = (byParent.get("root") ?? []).sort(byName).map(make);
  return { roots, byId, byParent, countDesc };
}

// "Cây danh mục Hub" tab: stat cards + the global parent–child tree (left) and a
// per-node detail panel (right) showing where that category is linked on each
// site. Tree is built client-side from the flat /categories list; the detail
// panel fetches /categories/{id}/sites/ on selection.
export default function CategoryTreeTab() {
  const overview = useCategoryOverview();
  const { data: categories = [], isLoading, isError, refetch } = useProductCategories();

  const [selectedId, setSelectedId] = useState(null);
  const [search, setSearch] = useState("");
  const [expandedKeys, setExpandedKeys] = useState([]);
  const [autoExpandParent, setAutoExpandParent] = useState(true);

  const { roots, byId, byParent, countDesc } = useMemo(
    () => buildTree(categories),
    [categories]
  );

  const o = overview.data ?? {};
  const cards = [
    {
      key: "total",
      label: "Tổng danh mục (đang dùng)",
      value: vi(o.hub_used),
      Icon: FolderTree,
      tint: "bg-blue-500/15 text-blue-300",
    },
    {
      key: "root",
      label: "Danh mục gốc",
      value: vi(o.root_count),
      Icon: Network,
      tint: "bg-green-500/15 text-success",
    },
    {
      key: "child",
      label: "Danh mục con",
      value: vi(o.child_count),
      Icon: Layers,
      tint: "bg-violet-500/15 text-violet-300",
    },
    {
      key: "deleted",
      label: "Danh mục đã xóa",
      value: vi(o.deleted_count),
      sub: "(ẩn khỏi cây)",
      Icon: Trash2,
      tint: "bg-red-500/15 text-danger",
    },
  ];

  const onSearch = (value) => {
    setSearch(value);
    if (!value) {
      setExpandedKeys([]);
      setAutoExpandParent(false);
      return;
    }
    const q = value.toLowerCase();
    const keys = [];
    const walk = (nodes, parents) => {
      for (const n of nodes) {
        if (n.title.toLowerCase().includes(q)) keys.push(...parents);
        if (n.children?.length) walk(n.children, [...parents, n.key]);
      }
    };
    walk(roots, []);
    setExpandedKeys([...new Set(keys)]);
    setAutoExpandParent(true);
  };

  // Highlight the matched substring in a tree row + show its subtree size.
  const titleRender = (node) => {
    const name = node.title;
    const q = search.trim().toLowerCase();
    const idx = q ? name.toLowerCase().indexOf(q) : -1;
    const count = countDesc(node.key);
    return (
      <span className="inline-flex items-center gap-2">
        <span>
          {idx === -1 ? (
            name
          ) : (
            <>
              {name.slice(0, idx)}
              <span className="bg-brand/25 text-ink">{name.slice(idx, idx + q.length)}</span>
              {name.slice(idx + q.length)}
            </>
          )}
        </span>
        {count > 0 && <span className="text-xs tabular-nums text-muted">{count}</span>}
      </span>
    );
  };

  const selected = selectedId != null ? byId.get(selectedId) : null;
  const links = useCategorySiteLinks(selectedId, { enabled: selectedId != null });
  const directChildren = selectedId != null ? (byParent.get(selectedId)?.length ?? 0) : 0;

  const linkColumns = [
    {
      key: "site",
      title: "Website",
      render: (_v, r) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{r.site_name}</p>
          <p className="truncate text-xs text-muted">{r.site_url}</p>
        </div>
      ),
    },
    {
      key: "status",
      title: "Trạng thái",
      width: 140,
      render: (_v, r) => <StatusDot status={r.site_status} />,
    },
    {
      key: "woo_category_id",
      dataIndex: "woo_category_id",
      title: "ID trên site",
      width: 110,
      align: "right",
      render: (v) => (v != null ? <span className="tabular-nums text-muted">{v}</span> : "—"),
    },
    {
      key: "woo_name",
      dataIndex: "woo_name",
      title: "Tên trên site (RAW)",
      width: 200,
      render: (v, r) =>
        r.linked ? v || "—" : <span className="text-muted">Chưa liên kết</span>,
    },
    {
      key: "last_synced_at",
      dataIndex: "last_synced_at",
      title: "Cập nhật gần nhất",
      width: 160,
      render: (v) => <span className="tabular-nums text-muted">{formatDate(v)}</span>,
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <StatCards cards={cards} loading={overview.isLoading} columns={4} />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
        {/* Tree */}
        <div className="rounded bg-surface-raised p-3 border border-border lg:col-span-2">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="font-display text-base font-semibold">Cây danh mục</h3>
            <span className="text-xs tabular-nums text-muted">{vi(o.hub_used)}</span>
          </div>
          <Input.Search
            allowClear
            placeholder="Tìm danh mục…"
            onChange={(e) => onSearch(e.target.value)}
            className="mb-2"
          />
          {isError ? (
            <ErrorState message="Không tải được cây danh mục" onRetry={refetch} />
          ) : isLoading ? (
            <p className="py-6 text-center text-sm text-muted">Đang tải cây danh mục…</p>
          ) : roots.length === 0 ? (
            <EmptyState title="Chưa có danh mục nào" hint="Đồng bộ danh mục từ một site để dựng cây." />
          ) : (
            <Tree
              treeData={roots}
              titleRender={titleRender}
              expandedKeys={expandedKeys}
              autoExpandParent={autoExpandParent}
              selectedKeys={selectedId != null ? [selectedId] : []}
              onExpand={(keys) => {
                setExpandedKeys(keys);
                setAutoExpandParent(false);
              }}
              onSelect={(keys) => setSelectedId(keys[0] ?? null)}
              className="max-h-[32rem] overflow-auto"
            />
          )}
        </div>

        {/* Detail panel */}
        <div className="rounded bg-surface-raised p-3 border border-border lg:col-span-3">
          {!selected ? (
            <div className="flex h-full min-h-64 items-center justify-center">
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="Chọn một danh mục để xem chi tiết"
              />
            </div>
          ) : (
            <>
              <h3 className="font-display text-xl font-bold">{selected.name}</h3>
              <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
                <div>
                  <p className="text-muted">Slug</p>
                  <p className="truncate font-medium">{selected.slug || "—"}</p>
                </div>
                <div>
                  <p className="text-muted">Danh mục cha</p>
                  <p className="truncate font-medium">
                    {selected.parent != null ? byId.get(selected.parent)?.name ?? "—" : "— (Gốc)"}
                  </p>
                </div>
                <div>
                  <p className="text-muted">Danh mục con</p>
                  <p className="font-medium tabular-nums">{directChildren}</p>
                </div>
                <div>
                  <p className="text-muted">Site đã liên kết</p>
                  <p className="font-medium tabular-nums">{selected.mapping_count ?? 0}</p>
                </div>
              </div>

              <h4 className="mt-4 font-display text-sm font-semibold">Liên kết với website</h4>
              {links.isError ? (
                <ErrorState message="Không tải được liên kết site" onRetry={links.refetch} />
              ) : (
                <Table
                  rowKey="site_id"
                  size="small"
                  className="mt-2"
                  loading={links.isLoading}
                  columns={linkColumns}
                  dataSource={links.data ?? []}
                  pagination={false}
                  scroll={{ y: 360 }}
                  locale={{ emptyText: "Chưa có site nào." }}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
