import { Button, Tooltip } from "antd";
import Link from "@tiptap/extension-link";
import Underline from "@tiptap/extension-underline";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  Bold,
  Heading2,
  Heading3,
  Italic,
  Link as LinkIcon,
  List,
  ListOrdered,
  Quote,
  Strikethrough,
  Underline as UnderlineIcon,
  Eraser,
} from "lucide-react";
import { useEffect } from "react";

// "Like Word" rich-text editor (TipTap). Produces HTML that the backend
// sanitizes before saving. Images are NOT handled here — they are separate
// attachments (see SiteNotesModal), so there is no image button.

function ToolbarButton({ title, active, disabled, onClick, children }) {
  return (
    <Tooltip title={title}>
      <Button
        type={active ? "primary" : "text"}
        size="small"
        disabled={disabled}
        onMouseDown={(e) => e.preventDefault()} // keep selection while clicking
        onClick={onClick}
        icon={children}
      />
    </Tooltip>
  );
}

export default function RichTextEditor({ value = "", onChange, minHeight = "120px" }) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Underline,
      Link.configure({ openOnClick: false, autolink: true }),
    ],
    content: value,
    editorProps: {
      attributes: { class: "richtext px-3 py-2", style: `min-height: ${minHeight}` },
    },
    onUpdate: ({ editor: ed }) => onChange?.(ed.getHTML()),
  });

  // Sync external value changes (e.g. switching into edit mode) into the editor
  // without clobbering it while the user is typing.
  useEffect(() => {
    if (editor && value !== editor.getHTML()) {
      editor.commands.setContent(value || "", false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, editor]);

  if (!editor) return null;

  const setLink = () => {
    const prev = editor.getAttributes("link").href || "";
    const url = window.prompt("Nhập đường dẫn (URL):", prev);
    if (url === null) return; // cancelled
    if (url === "") {
      editor.chain().focus().extendMarkRange("link").unsetLink().run();
      return;
    }
    editor.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
  };

  return (
    <div className="overflow-hidden rounded border border-slate-200">
      <div className="flex flex-wrap items-center gap-0.5 border-b border-slate-200 bg-slate-50 px-1.5 py-1">
        <ToolbarButton
          title="Đậm"
          active={editor.isActive("bold")}
          onClick={() => editor.chain().focus().toggleBold().run()}
        >
          <Bold size={15} />
        </ToolbarButton>
        <ToolbarButton
          title="Nghiêng"
          active={editor.isActive("italic")}
          onClick={() => editor.chain().focus().toggleItalic().run()}
        >
          <Italic size={15} />
        </ToolbarButton>
        <ToolbarButton
          title="Gạch chân"
          active={editor.isActive("underline")}
          onClick={() => editor.chain().focus().toggleUnderline().run()}
        >
          <UnderlineIcon size={15} />
        </ToolbarButton>
        <ToolbarButton
          title="Gạch ngang"
          active={editor.isActive("strike")}
          onClick={() => editor.chain().focus().toggleStrike().run()}
        >
          <Strikethrough size={15} />
        </ToolbarButton>
        <span className="mx-1 h-4 w-px bg-slate-300" />
        <ToolbarButton
          title="Tiêu đề lớn"
          active={editor.isActive("heading", { level: 2 })}
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        >
          <Heading2 size={15} />
        </ToolbarButton>
        <ToolbarButton
          title="Tiêu đề nhỏ"
          active={editor.isActive("heading", { level: 3 })}
          onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
        >
          <Heading3 size={15} />
        </ToolbarButton>
        <span className="mx-1 h-4 w-px bg-slate-300" />
        <ToolbarButton
          title="Danh sách"
          active={editor.isActive("bulletList")}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
        >
          <List size={15} />
        </ToolbarButton>
        <ToolbarButton
          title="Danh sách đánh số"
          active={editor.isActive("orderedList")}
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
        >
          <ListOrdered size={15} />
        </ToolbarButton>
        <ToolbarButton
          title="Trích dẫn"
          active={editor.isActive("blockquote")}
          onClick={() => editor.chain().focus().toggleBlockquote().run()}
        >
          <Quote size={15} />
        </ToolbarButton>
        <span className="mx-1 h-4 w-px bg-slate-300" />
        <ToolbarButton
          title="Chèn liên kết"
          active={editor.isActive("link")}
          onClick={setLink}
        >
          <LinkIcon size={15} />
        </ToolbarButton>
        <ToolbarButton
          title="Xóa định dạng"
          onClick={() =>
            editor.chain().focus().unsetAllMarks().clearNodes().run()
          }
        >
          <Eraser size={15} />
        </ToolbarButton>
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}
