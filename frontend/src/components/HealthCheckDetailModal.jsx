import { Descriptions, Modal } from "antd";

import { formatDateTime, formatResponseTime } from "../lib/format.js";
import HealthStatusBadge from "./HealthStatusBadge.jsx";

// Read-only detail of a single health-check row (the "Xem chi tiết" action).
export default function HealthCheckDetailModal({ check, open, onClose }) {
  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      title="Chi tiết lần kiểm tra"
      width={560}
    >
      {check && (
        <Descriptions column={1} bordered size="small" className="mt-2">
          <Descriptions.Item label="Website">
            {check.site_name}
          </Descriptions.Item>
          <Descriptions.Item label="Base URL">
            <a
              href={check.base_url}
              target="_blank"
              rel="noreferrer"
              className="text-brand hover:underline"
            >
              {check.base_url}
            </a>
          </Descriptions.Item>
          <Descriptions.Item label="Hosting">
            {check.hosting_name || "—"}
          </Descriptions.Item>
          <Descriptions.Item label="Loại kiểm tra">
            {check.check_type_display}
          </Descriptions.Item>
          <Descriptions.Item label="Thời gian kiểm tra">
            {formatDateTime(check.checked_at)}
          </Descriptions.Item>
          <Descriptions.Item label="Trạng thái">
            <HealthStatusBadge status={check.status} label={check.status_display} />
          </Descriptions.Item>
          <Descriptions.Item label="Thời gian phản hồi">
            {formatResponseTime(check.response_time_ms)}
          </Descriptions.Item>
          <Descriptions.Item label="Người thực hiện">
            {check.performed_by_name}
          </Descriptions.Item>
          <Descriptions.Item label="Chi tiết">
            {check.detail || "—"}
          </Descriptions.Item>
        </Descriptions>
      )}
    </Modal>
  );
}
