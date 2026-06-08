import { Button, Empty, Image, Modal, Pagination, Popconfirm, Skeleton, Upload } from "antd";
import DOMPurify from "dompurify";
import { Paperclip, Pencil, Plus, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import {
  useCreateSiteNote,
  useDeleteSiteNote,
  useSiteNotes,
  useUpdateSiteNote,
} from "../api/siteNotes.js";
import { formatDate } from "../lib/format.js";
import ErrorState from "./ErrorState.jsx";
import RichTextEditor from "./RichTextEditor.jsx";

const PAGE_SIZE = 10;

// True for "" / "<p></p>" / whitespace-only HTML — nothing worth saving.
const isEmptyHtml = (html) =>
  !html || html.replace(/<[^>]*>/g, "").replace(/&nbsp;/g, "").trim() === "";

const filesToSend = (fileList) =>
  fileList.map((f) => f.originFileObj).filter(Boolean);

export default function SiteNotesModal({ site, open, onClose }) {
  const siteId = site?.id ?? null;
  const [page, setPage] = useState(1);
  const [content, setContent] = useState("");
  const [newFiles, setNewFiles] = useState([]); // antd Upload fileList (pending)
  const [editingNote, setEditingNote] = useState(null); // note being edited | null
  const [existingImages, setExistingImages] = useState([]); // kept attachments (edit)
  const [removeIds, setRemoveIds] = useState([]); // attachment ids to delete (edit)

  const { data, isLoading, isError, refetch, isFetching } = useSiteNotes(siteId, {
    page,
    page_size: PAGE_SIZE,
  });
  const createNote = useCreateSiteNote(siteId);
  const updateNote = useUpdateSiteNote(siteId);
  const deleteNote = useDeleteSiteNote(siteId);

  const notes = data?.results ?? [];
  const total = data?.count ?? 0;

  const resetComposer = () => {
    setContent("");
    setNewFiles([]);
    setEditingNote(null);
    setExistingImages([]);
    setRemoveIds([]);
  };

  // Reset everything when the modal opens for a (possibly different) site.
  useEffect(() => {
    if (open) {
      setPage(1);
      resetComposer();
    }
  }, [open, siteId]);

  const startEdit = (note) => {
    setEditingNote(note);
    setContent(note.content || "");
    setExistingImages(note.images || []);
    setRemoveIds([]);
    setNewFiles([]);
  };

  const removeExisting = (img) => {
    setExistingImages((prev) => prev.filter((i) => i.id !== img.id));
    setRemoveIds((prev) => [...prev, img.id]);
  };

  const canSave =
    !isEmptyHtml(content) || newFiles.length > 0 || existingImages.length > 0;

  const handleSubmit = async () => {
    try {
      if (editingNote) {
        await updateNote.mutateAsync({
          id: editingNote.id,
          content,
          images: filesToSend(newFiles),
          removeImageIds: removeIds,
        });
        toast.success("Đã cập nhật ghi chú.");
      } else {
        await createNote.mutateAsync({
          siteId,
          content,
          images: filesToSend(newFiles),
        });
        toast.success("Đã lưu ghi chú.");
        setPage(1); // jump to newest
      }
      resetComposer();
    } catch (err) {
      toast.error(err.response?.data?.images || "Lưu ghi chú thất bại.");
    }
  };

  const handleDelete = async (note) => {
    try {
      await deleteNote.mutateAsync(note.id);
      toast.success("Đã xóa ghi chú.");
      if (editingNote?.id === note.id) resetComposer();
    } catch {
      toast.error("Xóa thất bại.");
    }
  };

  const saving = createNote.isPending || updateNote.isPending;

  const title = useMemo(
    () => (
      <div className="flex items-center gap-2">
        <span>Ghi chú website</span>
        {site && <span className="text-sm font-normal text-muted">· {site.name}</span>}
      </div>
    ),
    [site]
  );

  return (
    <Modal open={open} onCancel={onClose} footer={null} title={title} width={720} destroyOnHidden>
      {/* Composer (add / edit) */}
      <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50/60 p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium">
            {editingNote ? "Sửa ghi chú" : "Thêm ghi chú mới"}
          </span>
          {editingNote && (
            <Button type="link" size="small" onClick={resetComposer}>
              Hủy sửa
            </Button>
          )}
        </div>

        <RichTextEditor value={content} onChange={setContent} />

        {/* Existing attachments (edit mode) — removable */}
        {existingImages.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {existingImages.map((img) => (
              <div key={img.id} className="relative">
                <Image
                  src={img.url}
                  alt={img.original_name}
                  width={72}
                  height={72}
                  className="rounded object-cover"
                />
                <button
                  type="button"
                  onClick={() => removeExisting(img)}
                  className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-white text-danger shadow"
                  aria-label="Bỏ ảnh"
                >
                  <X size={13} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* New attachments */}
        <div className="mt-2 flex items-center justify-between gap-2">
          <Upload
            listType="picture-card"
            fileList={newFiles}
            beforeUpload={() => false} // keep files client-side; sent on save
            onChange={({ fileList }) => setNewFiles(fileList)}
            accept="image/*"
            multiple
          >
            <div className="flex flex-col items-center text-xs text-muted">
              <Paperclip size={16} />
              <span className="mt-1">Đính kèm ảnh</span>
            </div>
          </Upload>
          <Button
            type="primary"
            icon={editingNote ? <Pencil size={15} /> : <Plus size={15} />}
            loading={saving}
            disabled={!canSave}
            onClick={handleSubmit}
          >
            {editingNote ? "Cập nhật" : "Lưu ghi chú"}
          </Button>
        </div>
      </div>

      {/* History (newest first) */}
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted">Lịch sử ghi chú ({total})</h3>
      </div>

      {isError ? (
        <ErrorState message="Không tải được ghi chú" onRetry={refetch} />
      ) : isLoading ? (
        <Skeleton active paragraph={{ rows: 3 }} />
      ) : notes.length === 0 ? (
        <Empty description="Chưa có ghi chú nào" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div className="space-y-3">
          {notes.map((note, idx) => (
            <article
              key={note.id}
              className="rounded-lg border border-slate-200 p-3 shadow-card"
            >
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-xs text-muted">
                  {page === 1 && idx === 0 && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 font-semibold text-amber-700">
                      Mới nhất
                    </span>
                  )}
                  <span className="font-medium text-slate-700">{note.created_by_name}</span>
                  <span className="tabular-nums">{formatDate(note.created_at)}</span>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    size="small"
                    type="text"
                    icon={<Pencil size={14} />}
                    onClick={() => startEdit(note)}
                  />
                  <Popconfirm
                    title="Xóa ghi chú này?"
                    okText="Xóa"
                    cancelText="Hủy"
                    onConfirm={() => handleDelete(note)}
                  >
                    <Button size="small" type="text" danger icon={<Trash2 size={14} />} />
                  </Popconfirm>
                </div>
              </div>

              {note.content && (
                <div
                  className="richtext text-sm text-slate-800"
                  // Backend sanitizes on save; DOMPurify is a second layer at render.
                  dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(note.content) }}
                />
              )}

              {note.images?.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <Image.PreviewGroup>
                    {note.images.map((img) => (
                      <Image
                        key={img.id}
                        src={img.url}
                        alt={img.original_name}
                        width={72}
                        height={72}
                        className="rounded object-cover"
                      />
                    ))}
                  </Image.PreviewGroup>
                </div>
              )}
            </article>
          ))}

          {total > PAGE_SIZE && (
            <div className="flex justify-end pt-1">
              <Pagination
                size="small"
                current={page}
                pageSize={PAGE_SIZE}
                total={total}
                showSizeChanger={false}
                disabled={isFetching}
                onChange={setPage}
              />
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
