import { Button, Descriptions, Empty, Modal, Table, Tabs, Tag } from "antd";
import { RefreshCw } from "lucide-react";
import toast from "react-hot-toast";

import { useDomainInfo, useRefreshDomainInfo } from "../api/domainInfo.js";
import { useCan } from "../lib/AuthContext.jsx";
import { formatDate, formatDateTime, friendlySyncError } from "../lib/format.js";
import {
  BlacklistBadge,
  CheckStatusBadge,
  ExpiryBadge,
} from "./DomainStatusBadge.jsx";

// The DNS record types shown, in a stable, readable order.
const DNS_TYPES = ["A", "AAAA", "CNAME", "NS", "MX", "TXT"];

// Where the WHOIS answer came from (so admins know a .vn expiry is authoritative
// TENTEN data, not a guess).
const WHOIS_SOURCE_LABEL = {
  rdap: "RDAP",
  tenten: "TENTEN (GMO)",
  whois43: "WHOIS (port 43)",
};

// Tab-label status dot colours (compact glance at which check failed without
// opening every tab); mirrors the CheckStatusBadge palette.
const DOT = {
  ok: "bg-success",
  partial: "bg-warning",
  pending: "bg-info",
  error: "bg-danger",
  unsupported: "bg-overlay/30",
  skipped: "bg-overlay/30",
};

function TabLabel({ text, status }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${DOT[status] || "bg-overlay/30"}`}
        aria-hidden="true"
      />
      {text}
    </span>
  );
}

// Common header inside a tab: the check's full status badge + last-checked time.
function CheckHeader({ status, checkedAt }) {
  return (
    <div className="mb-2 flex items-center gap-2">
      <CheckStatusBadge status={status} />
      {checkedAt && (
        <span className="ml-auto text-xs text-muted">
          Kiểm tra: {formatDate(checkedAt)}
        </span>
      )}
    </div>
  );
}

function DnsTable({ records = {} }) {
  const rows = DNS_TYPES.filter((t) => t in records).map((type) => ({
    key: type,
    type,
    values: records[type] || [],
  }));
  return (
    <Table
      size="small"
      pagination={false}
      dataSource={rows}
      locale={{ emptyText: "Không có bản ghi DNS." }}
      columns={[
        { title: "Loại", dataIndex: "type", width: 90, render: (t) => <Tag>{t}</Tag> },
        {
          title: "Giá trị",
          dataIndex: "values",
          render: (values) =>
            values.length ? (
              <div className="flex flex-col gap-0.5">
                {values.map((v) => (
                  <span key={v} className="break-all font-mono text-xs">
                    {v}
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-muted">—</span>
            ),
        },
      ]}
    />
  );
}

// The five per-check tab bodies. Each renders ONLY its own section so the tab
// keeps a single concern in view.
function WhoisPane({ info }) {
  return (
    <>
      <CheckHeader status={info.whois_status} checkedAt={info.whois_checked_at} />
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label="Nhà đăng ký">
          {info.whois_registrar || "—"}
        </Descriptions.Item>
        <Descriptions.Item label="Ngày đăng ký">
          {formatDate(info.whois_created_at)}
        </Descriptions.Item>
        <Descriptions.Item label="Ngày hết hạn">
          <div className="flex items-center gap-2">
            <span className="tabular-nums">{formatDate(info.whois_expires_at)}</span>
            <ExpiryBadge days={info.whois_days_remaining} />
          </div>
        </Descriptions.Item>
        {info.whois_source && (
          <Descriptions.Item label="Nguồn">
            {WHOIS_SOURCE_LABEL[info.whois_source] || info.whois_source}
          </Descriptions.Item>
        )}
      </Descriptions>
    </>
  );
}

function DnsPane({ info }) {
  return (
    <>
      <CheckHeader status={info.dns_status} checkedAt={info.dns_checked_at} />
      <DnsTable records={info.dns_records} />
    </>
  );
}

function SslPane({ info }) {
  return (
    <>
      <CheckHeader status={info.ssl_status} checkedAt={info.ssl_checked_at} />
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label="Nhà phát hành">
          {info.ssl_issuer || "—"}
        </Descriptions.Item>
        <Descriptions.Item label="Hiệu lực từ">
          {formatDate(info.ssl_not_before)}
        </Descriptions.Item>
        <Descriptions.Item label="Hết hạn">
          <div className="flex items-center gap-2">
            <span className="tabular-nums">{formatDate(info.ssl_not_after)}</span>
            <ExpiryBadge days={info.ssl_days_remaining} />
          </div>
        </Descriptions.Item>
      </Descriptions>
    </>
  );
}

function BlacklistPane({ info }) {
  return (
    <>
      <CheckHeader status={info.blacklist_status} checkedAt={info.blacklist_checked_at} />
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted">Tổng kết:</span>
          <BlacklistBadge verdict={info.blacklist_verdict} />
        </div>
        {(info.blacklist_results || []).length > 0 && (
          <Table
            size="small"
            pagination={false}
            dataSource={info.blacklist_results.map((r, i) => ({ key: i, ...r }))}
            columns={[
              { title: "Danh sách", dataIndex: "list" },
              { title: "Đối tượng", dataIndex: "target" },
              {
                title: "Kết quả",
                dataIndex: "result",
                width: 130,
                render: (v) => <BlacklistBadge verdict={v} />,
              },
            ]}
          />
        )}
      </div>
    </>
  );
}

function GindexPane({ info }) {
  return (
    <>
      <CheckHeader status={info.gindex_status} checkedAt={info.gindex_checked_at} />
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label="Trạng thái">
          {info.gindex_status === "skipped" ? (
            <span className="text-muted">Bỏ qua — chưa cấu hình API key</span>
          ) : info.gindex_indexed == null ? (
            "—"
          ) : info.gindex_indexed ? (
            <Tag color="success">Đã được index</Tag>
          ) : (
            <Tag color="error">Chưa được index</Tag>
          )}
        </Descriptions.Item>
        {info.gindex_total_results != null && (
          <Descriptions.Item label="Số kết quả (ước tính)">
            <span className="tabular-nums">{info.gindex_total_results}</span>
          </Descriptions.Item>
        )}
      </Descriptions>
    </>
  );
}

// Per-site domain information panel, split into one tab per check (WHOIS / DNS /
// SSL / blacklist / Google index) so each tab shows only its own section.
// Read-only view of the backend snapshot + a "Làm mới" button that enqueues a
// Celery refresh; the query polls while any check is pending.
export default function DomainInfoModal({ site, open, onClose }) {
  const siteId = site?.id;
  const { data: info, isLoading } = useDomainInfo(siteId, { enabled: open });
  const refresh = useRefreshDomainInfo(siteId);
  const canRefresh = useCan()("domains.refresh_domaininfo");

  const handleRefresh = () => {
    refresh.mutate(
      { siteId },
      {
        onSuccess: () => toast.success("Đã kích hoạt kiểm tra tên miền."),
        onError: () => toast.error("Kích hoạt kiểm tra thất bại."),
      }
    );
  };

  const pending = info?.is_pending;
  const title = (
    <div className="flex items-center gap-2">
      <span>Thông tin tên miền</span>
      {info?.domain && (
        <span className="rounded-full bg-blue-500/15 px-2.5 py-0.5 text-xs font-semibold text-info">
          {info.domain}
        </span>
      )}
    </div>
  );

  const footer = (
    <div className="flex items-center justify-between gap-2">
      <span className="text-xs text-muted">
        {info?.last_refreshed_at
          ? `Cập nhật lần cuối: ${formatDateTime(info.last_refreshed_at)}`
          : ""}
      </span>
      <div className="flex gap-1.5">
        <Button onClick={onClose}>Đóng</Button>
        {canRefresh && (
          <Button
            type="primary"
            icon={<RefreshCw size={14} />}
            loading={refresh.isPending || pending}
            onClick={handleRefresh}
          >
            {pending ? "Đang kiểm tra…" : "Làm mới"}
          </Button>
        )}
      </div>
    </div>
  );

  const tabs = info && [
    { key: "whois", label: <TabLabel text="WHOIS" status={info.whois_status} />, children: <WhoisPane info={info} /> },
    { key: "dns", label: <TabLabel text="DNS" status={info.dns_status} />, children: <DnsPane info={info} /> },
    { key: "ssl", label: <TabLabel text="SSL/TLS" status={info.ssl_status} />, children: <SslPane info={info} /> },
    { key: "blacklist", label: <TabLabel text="Blacklist" status={info.blacklist_status} />, children: <BlacklistPane info={info} /> },
    { key: "gindex", label: <TabLabel text="Google Index" status={info.gindex_status} />, children: <GindexPane info={info} /> },
  ];

  return (
    <Modal open={open} onCancel={onClose} footer={footer} title={title} width={720}>
      {!info && !isLoading ? (
        <Empty description="Tên miền này chưa được kiểm tra." className="py-8">
          {canRefresh && (
            <Button type="primary" loading={refresh.isPending} onClick={handleRefresh}>
              Kiểm tra ngay
            </Button>
          )}
        </Empty>
      ) : (
        info && (
          <>
            <Tabs defaultActiveKey="whois" items={tabs} />
            {info.last_error && (
              <p className="text-xs text-muted">
                Ghi chú lỗi: {friendlySyncError(info.last_error)}
              </p>
            )}
          </>
        )
      )}
    </Modal>
  );
}
