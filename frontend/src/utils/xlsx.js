// Minimal .xlsx writer and reader, no dependencies.
//
// Writing: one sheet, a bold frozen header with an autofilter, dates as real Excel dates
// (dd.mm.yyyy), money and percentages as numbers with a format. The zip is stored without
// compression, which Excel, LibreOffice and Google Sheets all open.
// Reading: the first sheet of a workbook as rows of strings, for imports of two-column tables.
// Inflating uses the browser's DecompressionStream("deflate-raw").

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function zipStore(files) {
  const encoder = new TextEncoder();
  const parts = [];
  const central = [];
  let offset = 0;
  for (const { name, data } of files) {
    const nameBytes = encoder.encode(name);
    const body = typeof data === "string" ? encoder.encode(data) : data;
    const crc = crc32(body);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);
    local.setUint16(6, 0x0800, true); // UTF-8 names
    local.setUint16(8, 0, true); // stored
    local.setUint32(14, crc, true);
    local.setUint32(18, body.length, true);
    local.setUint32(22, body.length, true);
    local.setUint16(26, nameBytes.length, true);
    parts.push(new Uint8Array(local.buffer), nameBytes, body);

    const entry = new DataView(new ArrayBuffer(46));
    entry.setUint32(0, 0x02014b50, true);
    entry.setUint16(4, 20, true);
    entry.setUint16(6, 20, true);
    entry.setUint16(8, 0x0800, true);
    entry.setUint32(16, crc, true);
    entry.setUint32(20, body.length, true);
    entry.setUint32(24, body.length, true);
    entry.setUint16(28, nameBytes.length, true);
    entry.setUint32(42, offset, true);
    central.push(new Uint8Array(entry.buffer), nameBytes);
    offset += 30 + nameBytes.length + body.length;
  }
  const centralSize = central.reduce((acc, part) => acc + part.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, centralSize, true);
  end.setUint32(16, offset, true);
  return new Blob([...parts, ...central, new Uint8Array(end.buffer)], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

function xmlEscape(value) {
  return String(value)
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function columnName(index) {
  let name = "";
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  return name;
}

// style ids of styles.xml below
const STYLE = { text: 0, header: 1, date: 2, money: 3, number: 4, integer: 5, percent: 6 };

/** "2026-10-18" (or a timestamp starting with it) as an Excel serial day, else null. */
function excelDay(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ""));
  if (!match) return null;
  return (Date.UTC(+match[1], +match[2] - 1, +match[3]) - Date.UTC(1899, 11, 30)) / 86_400_000;
}

function cellXml(ref, value, type) {
  if (value === null || value === undefined || value === "") return "";
  if (type === "date") {
    const serial = excelDay(value);
    if (serial !== null) return `<c r="${ref}" s="${STYLE.date}"><v>${serial}</v></c>`;
  }
  if (["money", "number", "integer", "percent"].includes(type)) {
    const num = Number(value);
    if (Number.isFinite(num)) {
      const style = type === "number" && Number.isInteger(num) ? STYLE.integer : STYLE[type];
      return `<c r="${ref}" s="${style}"><v>${num}</v></c>`;
    }
  }
  return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xmlEscape(value)}</t></is></c>`;
}

const STYLES_XML = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="3"><numFmt numFmtId="164" formatCode="dd\\.mm\\.yyyy"/><numFmt numFmtId="165" formatCode="#,##0.00\\ &quot;₽&quot;"/><numFmt numFmtId="166" formatCode="#,##0.00"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="7">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="10" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs>
</styleSheet>`;

/**
 * Build a workbook of one sheet.
 * `columns`: [{ label, type: "text" | "date" | "money" | "number" | "integer" | "percent", width? }]
 * `rows`: arrays of raw values in column order (percent as a fraction, 0.12 = 12%).
 */
export function buildXlsx(sheetName, columns, rows) {
  const lastCol = columnName(Math.max(columns.length - 1, 0));
  const lastRow = rows.length + 1;
  const cols = columns
    .map((col, i) => `<col min="${i + 1}" max="${i + 1}" width="${col.width || (col.type === "text" ? 28 : 14)}" customWidth="1"/>`)
    .join("");
  const header = `<row r="1">${columns
    .map((col, i) => `<c r="${columnName(i)}1" s="${STYLE.header}" t="inlineStr"><is><t>${xmlEscape(col.label)}</t></is></c>`)
    .join("")}</row>`;
  const body = rows
    .map((row, r) => `<row r="${r + 2}">${row.map((value, c) => cellXml(`${columnName(c)}${r + 2}`, value, columns[c]?.type)).join("")}</row>`)
    .join("");
  const sheet = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<cols>${cols}</cols>
<sheetData>${header}${body}</sheetData>
<autoFilter ref="A1:${lastCol}${lastRow}"/>
</worksheet>`;
  // sheet names: at most 31 characters, none of []:*?/\
  const safeName = xmlEscape(String(sheetName || "Лист1").replace(/[[\]:*?/\\]/g, " ").slice(0, 31));
  return zipStore([
    {
      name: "[Content_Types].xml",
      data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>`,
    },
    {
      name: "_rels/.rels",
      data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`,
    },
    {
      name: "xl/workbook.xml",
      data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="${safeName}" sheetId="1" r:id="rId1"/></sheets>
<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'${safeName.replace(/'/g, "''")}'!$A$1:$${lastCol}$${lastRow}</definedName></definedNames>
</workbook>`,
    },
    {
      name: "xl/_rels/workbook.xml.rels",
      data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`,
    },
    { name: "xl/styles.xml", data: STYLES_XML },
    { name: "xl/worksheets/sheet1.xml", data: sheet },
  ]);
}

/** Save a workbook under `fileName` (".xlsx" is added when missing). */
export function downloadXlsx(fileName, sheetName, columns, rows) {
  const blob = buildXlsx(sheetName, columns, rows);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = /\.xlsx$/i.test(fileName) ? fileName : `${fileName}.xlsx`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// -- reading --

async function inflateRaw(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** The entries of a zip archive as { name: Uint8Array }, read from its central directory. */
async function unzip(buffer, wanted) {
  const view = new DataView(buffer);
  let end = -1;
  for (let i = buffer.byteLength - 22; i >= Math.max(0, buffer.byteLength - 65_557); i -= 1) {
    if (view.getUint32(i, true) === 0x06054b50) {
      end = i;
      break;
    }
  }
  if (end < 0) throw new Error("not_a_zip");
  const count = view.getUint16(end + 10, true);
  let ptr = view.getUint32(end + 16, true);
  const decoder = new TextDecoder();
  const files = {};
  for (let n = 0; n < count; n += 1) {
    if (view.getUint32(ptr, true) !== 0x02014b50) throw new Error("bad_zip");
    const method = view.getUint16(ptr + 10, true);
    const compressedSize = view.getUint32(ptr + 20, true);
    const nameLength = view.getUint16(ptr + 28, true);
    const extraLength = view.getUint16(ptr + 30, true);
    const commentLength = view.getUint16(ptr + 32, true);
    const localOffset = view.getUint32(ptr + 42, true);
    const name = decoder.decode(new Uint8Array(buffer, ptr + 46, nameLength));
    ptr += 46 + nameLength + extraLength + commentLength;
    if (!wanted(name)) continue;
    const localName = view.getUint16(localOffset + 26, true);
    const localExtra = view.getUint16(localOffset + 28, true);
    const data = new Uint8Array(buffer, localOffset + 30 + localName + localExtra, compressedSize);
    files[name] = method === 0 ? data : await inflateRaw(data);
  }
  return files;
}

function cellIndex(ref) {
  const letters = /^[A-Z]+/.exec(ref || "")?.[0] || "A";
  let index = 0;
  for (const ch of letters) index = index * 26 + (ch.charCodeAt(0) - 64);
  return index - 1;
}

/**
 * Rows of the first sheet of an .xlsx file as arrays of strings. Numbers keep Excel's raw
 * value ("120.5"), so a decimal comma or a currency format does not reach the parser.
 */
export async function readXlsxRows(file) {
  const buffer = await file.arrayBuffer();
  const files = await unzip(buffer, (name) =>
    name === "xl/sharedStrings.xml" || name === "xl/workbook.xml" || name === "xl/_rels/workbook.xml.rels" || /^xl\/worksheets\/sheet\d+\.xml$/.test(name)
  );
  const decoder = new TextDecoder();
  const parse = (name) => (files[name] ? new DOMParser().parseFromString(decoder.decode(files[name]), "application/xml") : null);

  const shared = [];
  const sst = parse("xl/sharedStrings.xml");
  if (sst) {
    for (const si of sst.getElementsByTagName("si")) {
      shared.push([...si.getElementsByTagName("t")].map((t) => t.textContent).join(""));
    }
  }

  // the first sheet in the workbook's order, not necessarily sheet1.xml
  let sheetPath = Object.keys(files).filter((n) => n.startsWith("xl/worksheets/")).sort()[0];
  const workbook = parse("xl/workbook.xml");
  const rels = parse("xl/_rels/workbook.xml.rels");
  const firstSheet = workbook?.getElementsByTagName("sheet")[0];
  const relId = firstSheet?.getAttribute("r:id") || firstSheet?.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id");
  if (relId && rels) {
    for (const rel of rels.getElementsByTagName("Relationship")) {
      if (rel.getAttribute("Id") === relId) {
        const target = rel.getAttribute("Target").replace(/^\/?(xl\/)?/, "");
        if (files[`xl/${target}`]) sheetPath = `xl/${target}`;
      }
    }
  }
  const sheet = parse(sheetPath);
  if (!sheet) throw new Error("no_sheet");

  const rows = [];
  for (const row of sheet.getElementsByTagName("row")) {
    const values = [];
    for (const c of row.getElementsByTagName("c")) {
      const type = c.getAttribute("t");
      let value = "";
      if (type === "s") value = shared[Number(c.getElementsByTagName("v")[0]?.textContent)] ?? "";
      else if (type === "inlineStr") value = [...c.getElementsByTagName("t")].map((t) => t.textContent).join("");
      else value = c.getElementsByTagName("v")[0]?.textContent ?? "";
      values[cellIndex(c.getAttribute("r"))] = value;
    }
    rows.push(Array.from(values, (v) => (v ?? "").trim()));
  }
  return rows.filter((r) => r.some(Boolean));
}

/** Rows of a .xlsx or a .csv/.txt file (";", tab or "," separated). */
export async function readTableFile(file) {
  if (/\.xlsx$/i.test(file.name)) return readXlsxRows(file);
  if (/\.xls$/i.test(file.name)) throw new Error("old_xls");
  const text = await file.text();
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const sep = [";", "\t", ","].find((s) => line.includes(s));
      return sep ? line.split(sep).map((v) => v.trim().replace(/^"|"$/g, "")) : [line];
    });
}
