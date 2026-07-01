import { Button, Modal, Select } from "antd";
import { FileSpreadsheet, Upload, X } from "lucide-react";
import { useRef, useState } from "react";

import { hostingLabel } from "../api/hostings.js";

// Bulk import from .xlsx. The file is parsed on the backend (SSOT). The user
// first picks a target hosting (optional) and a file in a modal, then imports.
// Expected columns: name, base_url, consumer_key, consumer_secret, plus an
// optional platform column (woocommerce | sapo; defaults to woocommerce).
export default function SiteImport({ onImport, pending, hostings = [] }) {
  const [open, setOpen] = useState(false);
  const [hosting, setHosting] = useState(null);
  const [file, setFile] = useState(null);
  const inputRef = useRef(null);

  const reset = () => {
    setHosting(null);
    setFile(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const close = () => {
    if (pending) return;
    setOpen(false);
    reset();
  };

  const handleImport = async () => {
    if (!file) return;
    await onImport({ file, hosting });
    setOpen(false);
    reset();
  };

  return (
    <>
      <div className="flex items-center gap-2 rounded bg-surface-raised p-2.5 border border-border">
        <span className="flex h-10 w-10 items-center justify-center rounded bg-green-500/15 text-success">
          <FileSpreadsheet size={24} />
        </span>
        <div className="text-sm">
          <p className="font-semibold">Import từ Excel (.xlsx)</p>
          <p className="text-muted">
            Cột yêu cầu:{" "}
            <span className="font-medium text-ink">
              name, base_url, consumer_key, consumer_secret
            </span>{" "}
            — tùy chọn: <span className="font-medium text-ink">platform</span>{" "}
            (woocommerce | sapo)
          </p>
        </div>
        <Button type="primary" ghost className="ml-auto" onClick={() => setOpen(true)}>
          Import Excel
        </Button>
      </div>

      <Modal
        open={open}
        onCancel={close}
        footer={null}
        destroyOnHidden
        title="Import website từ Excel"
      >
        <div className="grid gap-3">
          <div>
            <label className="mb-1 block text-sm font-medium">Hosting</label>
            <Select
              value={hosting}
              onChange={(v) => setHosting(v ?? null)}
              className="w-full"
              allowClear
              placeholder="Chọn hosting để gán cho các site import (tùy chọn)"
              options={hostings.map((h) => ({ value: h.id, label: hostingLabel(h) }))}
            />
            <p className="mt-1 text-xs text-muted">
              Mọi site trong file sẽ được gán vào hosting này. Để trống = không gán.
            </p>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium">File Excel (.xlsx)</label>
            <label className="flex cursor-pointer items-center gap-2 rounded border border-dashed border-border-strong px-3 py-2 text-sm hover:bg-white/5">
              <Upload size={16} className="text-brand" />
              <span className="font-medium text-brand">Chọn file</span>
              <input
                ref={inputRef}
                type="file"
                accept=".xlsx"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              {file && (
                <span className="ml-1 inline-flex items-center gap-1 text-muted">
                  {file.name}
                  <Button
                    type="text"
                    size="small"
                    icon={<X size={13} />}
                    aria-label="Bỏ chọn file"
                    onClick={(e) => {
                      e.preventDefault();
                      setFile(null);
                      if (inputRef.current) inputRef.current.value = "";
                    }}
                  />
                </span>
              )}
            </label>
          </div>

          <div className="flex gap-1 pt-1">
            <Button type="primary" loading={pending} disabled={!file} onClick={handleImport}>
              {pending ? "Đang import…" : "Bắt đầu import"}
            </Button>
            <Button onClick={close} disabled={pending}>
              Hủy
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
