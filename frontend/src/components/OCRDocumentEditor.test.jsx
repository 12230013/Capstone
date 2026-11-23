import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import OCRDocumentEditor from "./OCRDocumentEditor";
import { pagesToDocument, documentToPages } from "./ocrEditorDocument";

describe("unified review document",()=>{
  it("joins legacy OCR fragments and keeps tables and forms inline",()=>{
    const pages=[{page_number:1,blocks:[{type:"text",text:"Hope is\nthe light"},{type:"text",text:"that guides you."},{type:"table",rows:[["Item","Amount"],["Travel","500"]]},{type:"form",fields:[{label:"Name",value:"Karma"}]}]}];
    const doc=pagesToDocument(pages);
    expect(doc.content[0].content.map(n=>n.type)).toEqual(["paragraph","table","table"]);
    expect(doc.content[0].content[0].content[0].text).toBe("Hope is the light that guides you.");
    const restored=documentToPages(doc,pages);
    expect(restored[0].blocks[1].rows[1]).toEqual(["Travel","500"]);
    expect(restored[0].blocks[2].fields[0]).toEqual({label:"Name",value:"Karma"});
    expect(pagesToDocument(restored)).toEqual(doc);
  });

  it("has one editable canvas across pages with working undo and redo",async()=>{
    Range.prototype.getBoundingClientRect=()=>({top:0,left:0,right:0,bottom:0,width:0,height:0});
    Range.prototype.getClientRects=()=>[];
    const change=vi.fn(),user=userEvent.setup();
    render(<OCRDocumentEditor pages={[{page_number:1,text:"Original paragraph"},{page_number:2,text:"Second page"}]} disabled={false} onChange={change}/>);
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    await act(async()=>{screen.getByText("Original paragraph").textContent="Corrected paragraph";await new Promise(resolve=>setTimeout(resolve,0));});
    expect(change).toHaveBeenCalled();
    expect(screen.getByRole("button",{name:"Undo",exact:true})).toBeEnabled();
    await user.click(screen.getByRole("button",{name:"Undo",exact:true}));
    expect(screen.getByText("Original paragraph")).toBeVisible();
    await user.click(screen.getByRole("button",{name:"Redo",exact:true}));
    expect(screen.getByText("Corrected paragraph")).toBeVisible();
    expect(change.mock.lastCall[0].map(p=>p.page_number)).toEqual([1,2]);
  });
});

it("preserves verified merged cells and assigns readable widths to a wide table",()=>{
  const rows=[Array.from({length:14},(_,i)=>`Column ${i+1}`),Array.from({length:14},(_,i)=>`Value ${i+1}`)];
  const doc=pagesToDocument([{page_number:1,blocks:[{type:"table",rows,has_header:true,column_widths:Array(14).fill(100)}]}]);
  const table=doc.content[0].content[0];
  expect(table.content[0].content).toHaveLength(14);
  expect(table.content[0].content.every(cell=>cell.attrs.colwidth[0]>=100)).toBe(true);
  const merged=pagesToDocument([{page_number:1,blocks:[{type:"table",rows:[["PERSONAL DETAILS","","",""],["Name","Karma","Gender","Male"]],has_header:false,cell_spans:[[{column:0,colspan:4,rowspan:1}],[{column:0,colspan:1,rowspan:1},{column:1,colspan:1,rowspan:1},{column:2,colspan:1,rowspan:1},{column:3,colspan:1,rowspan:1}]]}]}]);
  const t=merged.content[0].content[0];expect(t.content[0].content).toHaveLength(1);
  expect(t.content[0].content[0].attrs.colspan).toBe(4);
  expect(t.content[0].content[0].type).toBe("tableCell");
});
