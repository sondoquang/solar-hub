import { Button, Empty, Input, Modal, Pagination, Spin, Tabs, Upload } from "antd";
import { Check, ImagePlus, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

import { useMediaImages, useUploadMedia } from "../api/media.js";

const PAGE_SIZE = 24;
const ACCEPT = "image/png,image/jpeg,image/gif,image/webp";

// WP-style media picker: upload new files or tick from the Hub's library.
// `onSelect(urls)` receives absolute URLs (already hosted by the backend) —
// the caller stores/embeds them; nothing here touches WooCommerce.
export default function MediaLibraryModal({
  open,
  onClose,
  onSelect,
  multiple = false,
  title = "Thư viện ảnh",
}) {
  const [tab, setTab] = useState("upload");
  const [selected, setSelected] = useState([]); // [{id, url}]
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [uploadingCount, setUploadingCount] = useState(0);

  const listQuery = useMediaImages({ page, page_size: PAGE_SIZE, search: search || undefined });
  const upload = useUploadMedia();

  // Fresh state each time the picker opens.
  useEffect(() => {
    if (open) {
      setSelected([]);
      setSearch("");
      setPage(1);
      setTab("upload");
    }
  }, [open]);

  const toggle = (img) => {
    setSelected((prev) => {
      const exists = prev.some((s) => s.id === img.id);
      if (exists) return prev.filter((s) => s.id !== img.id);
      return multiple ? [...prev, img] : [img];
    });
  };

  const customRequest = ({ file, onSuccess, onError }) => {
    setUploadingCount((n) => n + 1);
    upload.mutate(file, {
      onSuccess: (data) => {
        onSuccess(data);
        // Uploaded files are pre-selected (like WP) and shown in the library.
        toggle({ id: data.id, url: data.url });
        setTab("library");
        setPage(1);
      },
      onError: (e) => {
        onError(e);
        const detail = e?.response?.data?.image?.[0];
        toast.error(detail || `Tải ảnh "${file.name}" thất bại.`);
      },
      onSettled: () => setUploadingCount((n) => n - 1),
    });
  };

  const confirm = () => {
    onSelect(selected.map((s) => s.url));
    onClose();
  };

  const rows = listQuery.data?.results ?? [];

  const uploadTab = {
    key: "upload",
    label: "Tải tệp lên",
    children: (
      <Upload.Dragger
        multiple={multiple}
        accept={ACCEPT}
        showUploadList={false}
        customRequest={customRequest}
        disabled={uploadingCount > 0}
      >
        <div className="flex flex-col items-center gap-2 py-8 text-muted">
          {uploadingCount > 0 ? (
            <>
              <Spin />
              <p>Đang tải {uploadingCount} ảnh lên…</p>
            </>
          ) : (
            <>
              <UploadCloud size={36} strokeWidth={1.5} />
              <p className="font-medium text-text">Thả ảnh vào đây hoặc bấm để chọn tệp</p>
              <p className="text-xs">PNG / JPG / GIF / WebP, tối đa 5MB mỗi ảnh.</p>
            </>
          )}
        </div>
      </Upload.Dragger>
    ),
  };

  const libraryTab = {
    key: "library",
    label: "Thư viện",
    children: (
      <div className="flex flex-col gap-3">
        <Input.Search
          allowClear
          placeholder="Tìm theo tên tệp…"
          onSearch={(v) => {
            setSearch(v.trim());
            setPage(1);
          }}
        />
        {listQuery.isLoading ? (
          <div className="flex justify-center py-10">
            <Spin />
          </div>
        ) : listQuery.isError ? (
          <p className="py-10 text-center text-sm text-danger">
            Không tải được thư viện ảnh. Thử lại sau.
          </p>
        ) : rows.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={search ? "Không có ảnh khớp tìm kiếm" : "Chưa có ảnh — hãy tải lên"}
          />
        ) : (
          <div className="grid max-h-80 grid-cols-4 gap-2 overflow-y-auto sm:grid-cols-6">
            {rows.map((img) => {
              const isSelected = selected.some((s) => s.id === img.id);
              return (
                <button
                  key={img.id}
                  type="button"
                  title={img.original_name}
                  onClick={() => toggle(img)}
                  className={`relative aspect-square overflow-hidden rounded border-2 ${
                    isSelected ? "border-brand" : "border-transparent hover:border-border-strong"
                  }`}
                >
                  <img
                    src={img.url}
                    alt={img.original_name}
                    loading="lazy"
                    className="h-full w-full object-cover"
                  />
                  {isSelected && (
                    <span className="absolute right-1 top-1 rounded-full bg-brand p-0.5 text-white">
                      <Check size={12} />
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
        {(listQuery.data?.count ?? 0) > PAGE_SIZE && (
          <Pagination
            size="small"
            current={page}
            pageSize={PAGE_SIZE}
            total={listQuery.data.count}
            showSizeChanger={false}
            onChange={setPage}
            className="self-end"
          />
        )}
      </div>
    ),
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={title}
      width={720}
      footer={
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted">
            {selected.length > 0
              ? `Đã chọn ${selected.length} ảnh`
              : multiple
                ? "Chọn một hoặc nhiều ảnh"
                : "Chọn một ảnh"}
          </span>
          <div className="flex gap-2">
            <Button onClick={onClose}>Hủy</Button>
            <Button
              type="primary"
              icon={<ImagePlus size={14} />}
              disabled={selected.length === 0}
              onClick={confirm}
            >
              Dùng ảnh đã chọn
            </Button>
          </div>
        </div>
      }
    >
      <Tabs activeKey={tab} onChange={setTab} items={[uploadTab, libraryTab]} />
    </Modal>
  );
}
