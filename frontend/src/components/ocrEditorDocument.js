export const textBlock = text => ({ type: "text", text });
const textNode = text => text ? [{type:"text",text}] : [];
const paragraph = text => ({type:"paragraph",content:textNode(text)});
export function blocksToNodes(blocks) {
  const nodes=[];
  let pending="";
  const flush=()=>{if(pending) { nodes.push(...pending.split(/\n\s*\n/).map(t=>paragraph(t.replace(/\s*\n\s*/g," ")))); pending=""; }};
  for (const block of blocks) {
    if(block.type === "text") { pending += (pending ? " " : "")+(block.text || ""); continue; }
    flush();
    const rows=block.type === "form" ? block.fields.map(f=>[f.label,f.value]) : block.rows;
    if(rows?.length) {
      const count=Math.max(...rows.map(r=>r.length));
      const source=block.column_widths?.length === count ? block.column_widths : Array(count).fill(1);
      const total=source.reduce((a,b)=>a+b,0) || count;
      const actualColumns=block.cell_spans?.length ? Math.max(...block.cell_spans.map(row=>row.length)) : count;
      const minimum=actualColumns>=8 ? 120 : block.cell_spans?.length ? 25 : 70;
      const widths=source.map(w=>Math.max(minimum,Math.round(w/total*Math.max(760,actualColumns*120))));
      const covered=new Set();
      const content=rows.map((row,ri)=>{
        const cells=[];
        for(let ci=0;ci<count;) {
          if(covered.has(`${ri}:${ci}`)) {ci++;continue;}
          const span=block.cell_spans?.[ri]?.find(s=>s.column===ci);
          const colspan=Math.min(span?.colspan || 1,count-ci),rowspan=Math.min(span?.rowspan || 1,rows.length-ri);
          for(let r=ri+1;r<ri+rowspan;r++)for(let c=ci;c<ci+colspan;c++)covered.add(`${r}:${c}`);
          cells.push({type:ri===0 && block.type!=="form" && block.has_header!==false ? "tableHeader":"tableCell",attrs:{colspan,rowspan,colwidth:widths.slice(ci,ci+colspan)},content:[paragraph(row[ci] || "")]});
          ci+=colspan;
        }
        return {type:"tableRow",content:cells};
      });
      nodes.push({type:"table",attrs:{layoutKind:block.type === "form" ? "form":"table"},content});
    }
  }
  flush();return nodes.length ? nodes : [paragraph("")];
}
export function pagesToDocument(pages) {
  return {type:"doc",content:pages.map(p=>({type:"ocrPage",attrs:{pageNumber:p.page_number},content:p.editor_json?.content || blocksToNodes(p.blocks?.length ? p.blocks : [textBlock(p.text || "")])}))};
}
export function nodeText(node) {
  if(node.type === "text") return node.text || "";
  if(node.type === "hardBreak") return "\n";
  return (node.content || []).map(nodeText).join(["tableCell","tableHeader","bulletList","orderedList","listItem"].includes(node.type) ? "\n" : "");
}
export function nodesToBlocks(nodes) {
  return nodes.map(node=>node.type === "table" && node.attrs?.layoutKind === "form" && node.content.every(row=>row.content.length===2) ? {type:"form",fields:node.content.map(row=>({label:nodeText(row.content[0]),value:nodeText(row.content[1])}))} : node.type === "table" ? {type:"table",rows:node.content.map(row=>row.content.flatMap(cell=>[nodeText(cell),...Array(Math.max(0,(cell.attrs?.colspan || 1)-1)).fill("")]))} : textBlock(nodeText(node)));
}
export function documentToPages(doc, originalPages) {
  return doc.content.filter(n=>n.type === "ocrPage").map(node=>{
    const original=originalPages.find(p=>p.page_number===node.attrs.pageNumber);
    const blocks=nodesToBlocks(node.content || []);
    return {...original,page_number:node.attrs.pageNumber,blocks,editor_json:{type:"doc",content:node.content || []}};
  });
}
