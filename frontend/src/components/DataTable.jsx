import { Button, Checkbox, Popover, Skeleton, Table, Tooltip } from "antd";
import { RotateCw, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";

// Reusable table wrapper that enforces the project-wide table rules so every
// table behaves the same (see docs/frontend/PROJECT_RULE.md §7a):
//   - column-visibility selector in the toolbar (toggle which columns show);
//   - server-driven pagination — the page-size changer re-queries via onChange;
//   - min-width columns + ellipsis ("…") when a cell overflows on narrow screens;
//   - a manual "Tải lại" (refresh) button.
//
// Pass antd <Table> props through (dataSource, rowKey, loading, pagination,
// rowSelection, onChange, …). Each column should carry a `width` (its min width)
// and a stable `key`/`dataIndex` (used as the visibility toggle id). A column
// opts out of hiding with `hideable: false` and out of ellipsis with
// `ellipsis: false` (use it for action columns).
const DEFAULT_COL_WIDTH = 160;

const colKey = (c) => c.key ?? c.dataIndex;

export default function DataTable({
  columns,
  title,
  toolbarExtra,
  onRefresh,
  refreshing = false,
  scroll,
  ...tableProps
}) {
  const [hiddenKeys, setHiddenKeys] = useState(() => new Set());

  const toggleable = columns.filter((c) => colKey(c) != null && c.hideable !== false);

  const visibleColumns = useMemo(
    () =>
      columns
        .filter((c) => !hiddenKeys.has(colKey(c)))
        // Default every column to ellipsis + a min width; columns can override.
        .map((c) => ({ ellipsis: true, width: DEFAULT_COL_WIDTH, ...c })),
    [columns, hiddenKeys]
  );

  // Sum of the visible columns' min widths → horizontal scroll on screens too
  // narrow to fit them, instead of squashing the data.
  const scrollX = useMemo(
    () => visibleColumns.reduce((sum, c) => sum + (typeof c.width === "number" ? c.width : DEFAULT_COL_WIDTH), 0),
    [visibleColumns]
  );

  const toggle = (key, checked) =>
    setHiddenKeys((prev) => {
      const next = new Set(prev);
      if (checked) next.delete(key);
      else next.add(key);
      return next;
    });

  // Initial load (loading + no data yet): render shimmer rows instead of antd's
  // spinner overlay so the table keeps its shape while data arrives. Once data
  // exists, `loading` (e.g. a refetch) falls back to the normal spinner.
  const isSkeleton = tableProps.loading && !(tableProps.dataSource?.length > 0);
  const skeletonRowCount = Math.min(tableProps.pagination?.pageSize || 6, 10);

  const skeletonProps = isSkeleton
    ? {
        loading: false,
        rowSelection: undefined,
        pagination: false,
        rowKey: "__skeletonKey",
        dataSource: Array.from({ length: skeletonRowCount }, (_, i) => ({
          __skeletonKey: i,
        })),
      }
    : null;

  const renderColumns = isSkeleton
    ? visibleColumns.map((c) => ({
        ...c,
        render: () => <Skeleton.Input active size="small" block />,
      }))
    : visibleColumns;

  const columnPicker = (
    <div className="flex max-h-72 min-w-44 flex-col gap-1.5 overflow-auto py-1">
      {toggleable.map((c) => {
        const key = colKey(c);
        return (
          <Checkbox
            key={key}
            checked={!hiddenKeys.has(key)}
            onChange={(e) => toggle(key, e.target.checked)}
          >
            {typeof c.title === "string" ? c.title : key}
          </Checkbox>
        );
      })}
    </div>
  );

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 px-1 pb-2.5">
        <div className="flex min-w-0 items-center gap-2">{title}{toolbarExtra}</div>
        <div className="flex items-center gap-1">
          <Popover
            content={columnPicker}
            title="Hiển thị cột"
            trigger="click"
            placement="bottomRight"
          >
            <Button icon={<SlidersHorizontal size={16} />}>Cột</Button>
          </Popover>
          {onRefresh && (
            <Tooltip title="Tải lại dữ liệu">
              <Button
                icon={<RotateCw size={16} />}
                loading={refreshing}
                onClick={onRefresh}
                aria-label="Tải lại"
              >
                Tải lại
              </Button>
            </Tooltip>
          )}
        </div>
      </div>
      <Table
        columns={renderColumns}
        scroll={{ x: scrollX, ...scroll }}
        {...tableProps}
        {...skeletonProps}
      />
    </div>
  );
}
