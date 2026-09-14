// Adapted from the existing resume-tracker Tencent Docs decoder. No source-specific filters.
import { inflateSync } from "node:zlib";
function cleanCell(value) {
  return String(value || '')
  // Wire control characters are intentionally removed while preserving line breaks.
  // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u0006\u0008-\u001f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}


export function parseJsonp(jsonp) {
  const start = jsonp.indexOf('(');
  const end = jsonp.lastIndexOf(')');
  if (start < 0 || end <= start) throw new Error('Tencent Docs returned an unexpected response.');
  return JSON.parse(jsonp.slice(start + 1, end));
}

export function extractAttributedText(payload) {
  const attributed = payload?.clientVars?.collab_client_vars?.initialAttributedText?.text?.[0];
  if (!attributed) throw new Error('Tencent Docs attributed text was not found.');

  if (typeof attributed === 'string') {
    return Buffer.from(attributed, 'base64').toString('utf8');
  }

  if (!Array.isArray(attributed.chunks) || attributed.chunks.length === 0) {
    throw new Error('Tencent Docs attributed text used an unsupported object format.');
  }

  const chunks = [...attributed.chunks].sort(
    (left, right) => Number(left.index) - Number(right.index)
  );
  const buffers = chunks.map((chunk, position) => {
    const index = Number(chunk.index);
    if (!Number.isInteger(index) || index !== position) {
      throw new Error(`Tencent Docs chunk sequence was incomplete at position ${position}.`);
    }
    if (typeof chunk.command !== 'string' || !chunk.command) {
      throw new Error(`Tencent Docs chunk command was not found at index ${index}.`);
    }
    if (position === 0 && String(chunk.gcp_start ?? '0') !== '0') {
      throw new Error('Tencent Docs chunk sequence did not start at the beginning of the document.');
    }
    if (
      position > 0 &&
      chunks[position - 1].gcp_end != null &&
      chunk.gcp_start != null &&
      String(chunks[position - 1].gcp_end) !== String(chunk.gcp_start)
    ) {
      throw new Error(`Tencent Docs chunk sequence contained a gap before index ${index}.`);
    }
    return Buffer.from(chunk.command, 'base64');
  });
  return Buffer.concat(buffers).toString('utf8');
}


function readVarint(buffer, start) {
  let value = 0n;
  let shift = 0n;
  let position = start;
  while (position < buffer.length && position - start < 10) {
    const byte = buffer[position];
    position += 1;
    value |= BigInt(byte & 0x7f) << shift;
    if (!(byte & 0x80)) return { value, position };
    shift += 7n;
  }
  throw new Error('Invalid protobuf varint.');
}

function parseProtobuf(buffer, depth = 0) {
  let position = 0;
  const fields = [];
  while (position < buffer.length) {
    const key = readVarint(buffer, position);
    position = key.position;
    const field = Number(key.value >> 3n);
    const wire = Number(key.value & 7n);
    if (field <= 0 || field > 100000) throw new Error('Invalid protobuf field.');

    if (wire === 0) {
      const item = readVarint(buffer, position);
      position = item.position;
      fields.push({ field, wire, value: item.value });
      continue;
    }
    if (wire === 1 || wire === 5) {
      const size = wire === 1 ? 8 : 4;
      if (position + size > buffer.length) throw new Error('Invalid fixed protobuf value.');
      fields.push({ field, wire, value: buffer.subarray(position, position + size) });
      position += size;
      continue;
    }
    if (wire !== 2) throw new Error(`Unsupported protobuf wire type: ${wire}`);

    const lengthValue = readVarint(buffer, position);
    position = lengthValue.position;
    const length = Number(lengthValue.value);
    if (position + length > buffer.length) throw new Error('Invalid protobuf message length.');
    const value = buffer.subarray(position, position + length);
    position += length;
    let child = null;
    if (depth < 14 && length > 0) {
      try {
        child = parseProtobuf(value, depth + 1);
      } catch {
        child = null;
      }
    }
    const text = value.toString('utf8');
    const printable =
      !text.includes('\uFFFD') &&
      /[\u4e00-\u9fffA-Za-z0-9]/.test(text) &&
      ![...text].some((character) => {
        const code = character.charCodeAt(0);
        return code < 32 && !['\n', '\r', '\t'].includes(character);
      });
    fields.push({ field, wire, value, child, text: printable ? text : '' });
  }
  return fields;
}

function nodesAtPath(fields, path, index = 0) {
  if (index >= path.length) return [fields];
  const nodes = [];
  for (const item of fields) {
    if (item.field === path[index] && item.child) {
      nodes.push(...nodesAtPath(item.child, path, index + 1));
    }
  }
  return nodes;
}

function collectTexts(fields, output = []) {
  for (const item of fields) {
    if (item.text) output.push(item.text);
    if (item.child) collectTexts(item.child, output);
  }
  return output;
}

function directVarint(fields, field, fallback = 0) {
  const item = fields.find((entry) => entry.field === field && entry.wire === 0);
  return item ? Number(item.value) : fallback;
}

function parseRelatedSheet(encoded) {
  const tree = parseProtobuf(inflateSync(Buffer.from(encoded, 'base64'), { maxOutputLength: 8_000_000 }));
  const sheet = nodesAtPath(tree, [1, 5, 19])[0];
  const pool = nodesAtPath(tree, [1, 5, 19, 5])[0];
  if (!sheet || !pool) throw new Error('Tencent sheet cell table was not found.');

  const stringPool = pool
    .filter((item) => item.field === 1 && item.child)
    .map((item) => item.child.find((child) => child.field === 1 && child.text)?.text || '');
  const linkPool = pool
    .filter((item) => item.field === 2 && item.child)
    .map((item) => collectTexts(item.child).find((text) => /^https?:\/\//i.test(text)) || '');
  const rows = new Map();

  for (const cell of sheet.filter((item) => item.field === 6 && item.child)) {
    const row = directVarint(cell.child, 1, 0);
    const column = directVarint(cell.child, 2, 0);
    const data = cell.child.find((item) => item.field === 3 && item.child)?.child || [];
    const valueType = directVarint(data, 1, 0);
    const referenceFields = data.find((item) => item.field === 2 && item.child)?.child || [];
    const reference = directVarint(referenceFields, 1, 0);
    const value = valueType === 4 ? stringPool[reference] || '' : valueType === 6 ? linkPool[reference] || '' : '';
    if (!rows.has(row)) rows.set(row, []);
    rows.get(row)[column] = cleanCell(value);
  }
  return [...rows.entries()].sort((left, right) => left[0] - right[0]).map(([, values]) => values);
}

export function parseSheetResponse(jsonp) {
  const payload = parseJsonp(jsonp);
  const collab = payload?.clientVars?.collab_client_vars;
  const blockDatas = collab?.initialAttributedText?.text?.[0]?.block_datas;
  if (!Array.isArray(blockDatas) || blockDatas.length === 0) {
    throw new Error('Tencent sheet block data was not found.');
  }
  return {
    maxRow: Number(collab.maxRow || 0),
    rows: blockDatas.flatMap((block) => parseRelatedSheet(block.related_sheet)),
  };
}
