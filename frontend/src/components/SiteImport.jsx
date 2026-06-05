import { FileSpreadsheet } from "lucide-react";
import { useRef, useState } from "react";

// Bulk import from .xlsx. The file is parsed on the backend (SSOT); this is
// just an upload control. Expected columns: name, base_url, consumer_key, consumer_secret.
export default function SiteImport({ onImport, pending }) {
  const inputRef = useRef(null);
  const [fileName, setFileName] = useState("");

  const handleChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    await onImport(file);
    setFileName("");
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="flex items-center gap-4 rounded-xl bg-white p-5 shadow-card">
      <span className="flex h-12 w-12 items-center justify-center rounded-lg bg-green-50 text-success">
        <FileSpreadsheet size={24} />
      </span>
      <div className="text-sm">
        <p className="font-semibold">Import từ Excel (.xlsx)</p>
        <p className="text-muted">
          Cột yêu cầu: <span className="font-medium text-ink">name, base_url, consumer_key, consumer_secret</span>
        </p>
      </div>
      <label className="ml-auto cursor-pointer rounded-lg border border-brand px-5 py-2.5 text-sm font-semibold text-brand transition-colors hover:bg-amber-50">
        {pending ? "Đang import…" : "Chọn file Excel"}
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx"
          className="hidden"
          disabled={pending}
          onChange={handleChange}
        />
      </label>
      {fileName && <span className="text-sm text-muted">{fileName}</span>}
    </div>
  );
}
