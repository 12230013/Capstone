import { useEffect } from "react";
import { Node, mergeAttributes } from "@tiptap/core";
import { useEditor, EditorContent, useEditorState } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { TableKit, Table } from "@tiptap/extension-table";
import Placeholder from "@tiptap/extension-placeholder";
import { pagesToDocument, documentToPages } from "./ocrEditorDocument";

const OCRPage=Node.create({
  name:"ocrPage",group:"block",content:"block+",isolating:true,defining:true,
  addAttributes:()=>({pageNumber:{default:1}}),
  parseHTML:()=>[{tag:"section[data-ocr-page]"}],
  renderHTML:({node,HTMLAttributes})=>["section",mergeAttributes(HTMLAttributes,{"data-ocr-page":node.attrs.pageNumber,"class":"ocr-editor-page"}),0],
});

const Document=Node.create({name:"doc",topNode:true,content:"ocrPage+"});
const ReviewTable=Table.extend({
  addAttributes() { return {...this.parent?.(),layoutKind:{default:"table",parseHTML:el=>el.getAttribute("data-layout-kind") || "table",renderHTML:attrs=>({"data-layout-kind":attrs.layoutKind})}}; },
});

export default function OCRDocumentEditor({pages,onChange,disabled}) {
  const editor=useEditor({
    extensions:[StarterKit.configure({document:false,trailingNode:false,codeBlock:false,link:false}),Document,OCRPage,TableKit.configure({table:false}),ReviewTable.configure({resizable:true}),Placeholder.configure({placeholder:"Review and edit your document here…"})],
    content:pagesToDocument(pages),editable:!disabled,
    editorProps:{attributes:{role:"textbox","aria-label":"Document review editor","aria-multiline":"true"}},
    onUpdate:({editor})=>onChange(documentToPages(editor.getJSON(),pages)),
  });
  useEffect(()=>{editor?.setEditable(!disabled,false);},[editor,disabled]);
  const state=useEditorState({editor,selector:({editor})=>editor ? {undo:editor.can().undo(),redo:editor.can().redo(),table:editor.isActive("table"),bold:editor.isActive("bold"),italic:editor.isActive("italic")} : {}});
  if(!editor) return null;
  const action=(label,command,enabled=true,pressed)=> <button type="button" disabled={disabled || !enabled} aria-pressed={pressed} onMouseDown={e=>e.preventDefault()} onClick={()=>command(editor.chain().focus()).run()}>{label}</button>;
  return <div className="ocr-document-editor">
    <div className="ocr-editor-toolbar" role="toolbar" aria-label="Document editing tools">
      {action("Undo",c=>c.undo(),state.undo)}{action("Redo",c=>c.redo(),state.redo)}
      {action("Bold",c=>c.toggleBold(),true,state.bold)}{action("Italic",c=>c.toggleItalic(),true,state.italic)}
      {action("Bulleted list",c=>c.toggleBulletList())}
      {action("Insert table",c=>c.insertTable({rows:3,cols:3,withHeaderRow:true}))}
      {action("Insert form",c=>c.insertContent({type:"table",attrs:{layoutKind:"form"},content:[{type:"tableRow",content:[{type:"tableCell",content:[{type:"paragraph",content:[{type:"text",text:"Field name"}]}]},{type:"tableCell",content:[{type:"paragraph",content:[{type:"text",text:"Value"}]}]}]}]}))}
      {state.table && <>{action("Add row",c=>c.addRowAfter())}{action("Add column",c=>c.addColumnAfter())}{action("Remove row",c=>c.deleteRow())}{action("Remove column",c=>c.deleteColumn())}{action("Delete table",c=>c.deleteTable())}</>}
    </div>
    <p className="ocr-editor-tip">Edit directly in the document. Use Tab to move between cells. Undo: Ctrl/⌘ Z · Redo: Ctrl/⌘ Shift Z.</p>
    <EditorContent editor={editor}/>
  </div>;
}
