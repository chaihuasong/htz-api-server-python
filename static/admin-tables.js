/*
 * 管理后台数据表：列顺序、真正的 xlsx 导出、全屏。
 * 不依赖第三方库。浏览器通过 /static/admin-tables.js 加载；
 * Node 测试可 require 本文件里的纯函数。
 */
(function (root, factory) {
    const api = factory();
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (typeof root !== 'undefined') root.AdminTables = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    const STORAGE_PREFIX = 'htz-admin-col-order:';
    const registry = Object.create(null);

    function uniqueStrings(list) {
        const out = [];
        (Array.isArray(list) ? list : []).forEach(key => {
            if (typeof key !== 'string' || !key || out.indexOf(key) !== -1) return;
            out.push(key);
        });
        return out;
    }

    // saved 里已经不存在的列丢掉；默认列里新增的列插回它相对剩余列的原位置。
    function resolveColumnOrder(defaultKeys, savedKeys) {
        const defaults = uniqueStrings(defaultKeys);
        const saved = uniqueStrings(savedKeys).filter(key => defaults.indexOf(key) !== -1);
        if (!saved.length) return defaults.slice();
        const result = saved.slice();
        defaults.forEach((key, defIdx) => {
            if (result.indexOf(key) !== -1) return;
            let insertAt = result.length;
            for (let i = 0; i < result.length; i++) {
                if (defaults.indexOf(result[i]) > defIdx) {
                    insertAt = i;
                    break;
                }
            }
            result.splice(insertAt, 0, key);
        });
        return result;
    }

    function storageKey(id) {
        return STORAGE_PREFIX + id;
    }

    function loadOrder(id) {
        if (typeof localStorage === 'undefined') return [];
        try {
            const parsed = JSON.parse(localStorage.getItem(storageKey(id)) || '[]');
            return Array.isArray(parsed) ? parsed : [];
        } catch (e) {
            return [];
        }
    }

    function saveOrder(id, keys) {
        if (typeof localStorage === 'undefined') return;
        localStorage.setItem(storageKey(id), JSON.stringify(uniqueStrings(keys)));
    }

    function clearOrder(id) {
        if (typeof localStorage === 'undefined') return;
        localStorage.removeItem(storageKey(id));
    }

    function register(spec) {
        if (!spec || !spec.id) return;
        registry[spec.id] = spec;
        if (!Array.isArray(spec.rows)) spec.rows = [];
    }

    function setRows(id, rows) {
        if (!registry[id]) return;
        registry[id].rows = Array.isArray(rows) ? rows : [];
    }

    function getSpec(id) {
        return registry[id] || null;
    }

    function defaultKeys(spec) {
        return (spec.columns || []).map(col => col.key);
    }

    function resolvedOrder(spec) {
        return resolveColumnOrder(defaultKeys(spec), loadOrder(spec.id));
    }

    function isCustomOrder(spec) {
        return resolvedOrder(spec).join('\0') !== defaultKeys(spec).join('\0');
    }

    function composeScope(spec) {
        const meta = spec && typeof spec.scope === 'function' ? spec.scope() : {};
        const count = spec && Array.isArray(spec.rows) ? spec.rows.length : 0;
        const filterText = meta.filterText || '无';
        const sortText = meta.sortText || '无';
        const coverage = meta.coverage || '';
        const text = `筛选：${filterText} · 排序：${sortText} · 列顺序：${spec && isCustomOrder(spec) ? '已自定义' : '默认'} · 共 ${count} 条。${coverage}`;
        return { text, partial: !!meta.partial, count, raw: meta };
    }

    function xmlText(value) {
        return String(value == null ? '' : value)
            .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function xmlAttr(value) {
        return xmlText(value).replace(/"/g, '&quot;');
    }

    function colName(index) {
        let n = index + 1;
        let s = '';
        while (n > 0) {
            const m = (n - 1) % 26;
            s = String.fromCharCode(65 + m) + s;
            n = Math.floor((n - 1) / 26);
        }
        return s;
    }

    function pad2(n) {
        return String(n).padStart(2, '0');
    }

    function parseDateParts(value) {
        const text = String(value == null ? '' : value).trim();
        const m = text.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/);
        if (!m) return null;
        const year = Number(m[1]);
        const month = Number(m[2]);
        const day = Number(m[3]);
        const hour = m[4] == null ? 0 : Number(m[4]);
        const minute = m[5] == null ? 0 : Number(m[5]);
        const second = m[6] == null ? 0 : Number(m[6]);
        if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59 || second > 59) return null;
        const probe = new Date(Date.UTC(year, month - 1, day));
        if (probe.getUTCFullYear() !== year || probe.getUTCMonth() !== month - 1 || probe.getUTCDate() !== day) return null;
        return { year, month, day, hour, minute, second, hasTime: m[4] != null };
    }

    function excelSerial(parts) {
        const utc = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
        const epoch = Date.UTC(1899, 11, 30);
        return (utc - epoch) / 86400000;
    }

    function normalizeCell(value, type) {
        if (value == null) return { kind: 'empty' };
        if (type === 'number' || type === 'percent') {
            if (value === '') return { kind: 'empty' };
            const n = typeof value === 'number' ? value : Number(String(value).trim());
            if (!Number.isFinite(n)) return { kind: 'text', value: String(value) };
            if (type === 'percent') return { kind: 'percent', value: n / 100 };
            return { kind: 'number', value: n };
        }
        if (type === 'date' || type === 'datetime') {
            if (value === '') return { kind: 'empty' };
            const parts = parseDateParts(value);
            if (!parts) return { kind: 'text', value: String(value) };
            const kind = type === 'date' && !parts.hasTime ? 'date' : 'datetime';
            return { kind, value: excelSerial(parts) };
        }
        if (value === '') return { kind: 'empty' };
        return { kind: 'text', value: String(value) };
    }

    function numberText(n) {
        if (Object.is(n, -0)) return '0';
        if (Number.isInteger(n) && Math.abs(n) <= Number.MAX_SAFE_INTEGER) return String(n);
        return String(n);
    }

    function cellXml(ref, cell) {
        if (!cell || cell.kind === 'empty') return '';
        if (cell.kind === 'number') return `<c r="${ref}"><v>${numberText(cell.value)}</v></c>`;
        if (cell.kind === 'percent') return `<c r="${ref}" s="3"><v>${numberText(cell.value)}</v></c>`;
        if (cell.kind === 'date') return `<c r="${ref}" s="1"><v>${numberText(cell.value)}</v></c>`;
        if (cell.kind === 'datetime') return `<c r="${ref}" s="2"><v>${numberText(cell.value)}</v></c>`;
        return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xmlText(cell.value)}</t></is></c>`;
    }

    function sheetXml(rows) {
        const xmlRows = rows.map((row, rIndex) => {
            const cells = row.map((cell, cIndex) => cellXml(colName(cIndex) + (rIndex + 1), cell)).join('');
            return `<row r="${rIndex + 1}">${cells}</row>`;
        }).join('');
        const lastCol = rows.reduce((max, row) => Math.max(max, row.length), 1);
        const dim = `A1:${colName(lastCol - 1)}${Math.max(rows.length, 1)}`;
        return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
            `<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">` +
            `<dimension ref="${dim}"/>` +
            `<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>` +
            `<sheetData>${xmlRows}</sheetData>` +
            `</worksheet>`;
    }

    function stylesXml() {
        return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
            `<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">` +
            `<numFmts count="3">` +
            `<numFmt numFmtId="164" formatCode="yyyy-mm-dd"/>` +
            `<numFmt numFmtId="165" formatCode="yyyy-mm-dd hh:mm:ss"/>` +
            `<numFmt numFmtId="166" formatCode="0.0%"/>` +
            `</numFmts>` +
            `<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>` +
            `<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>` +
            `<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>` +
            `<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>` +
            `<cellXfs count="4">` +
            `<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>` +
            `<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>` +
            `<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>` +
            `<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>` +
            `</cellXfs>` +
            `</styleSheet>`;
    }

    function workbookXml() {
        return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
            `<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">` +
            `<sheets>` +
            `<sheet name="${xmlAttr('数据')}" sheetId="1" r:id="rId1"/>` +
            `<sheet name="${xmlAttr('导出说明')}" sheetId="2" r:id="rId2"/>` +
            `</sheets></workbook>`;
    }

    function contentTypesXml() {
        return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
            `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">` +
            `<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>` +
            `<Default Extension="xml" ContentType="application/xml"/>` +
            `<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>` +
            `<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>` +
            `<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>` +
            `<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>` +
            `</Types>`;
    }

    function rootRels() {
        return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
            `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
            `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>` +
            `</Relationships>`;
    }

    function workbookRels() {
        return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
            `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
            `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>` +
            `<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>` +
            `<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>` +
            `</Relationships>`;
    }

    function crc32(bytes) {
        let c = ~0;
        for (let i = 0; i < bytes.length; i++) {
            c ^= bytes[i];
            for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xEDB88320 & -(c & 1));
        }
        return (~c) >>> 0;
    }

    function u16(view, offset, value) {
        view.setUint16(offset, value, true);
    }

    function u32(view, offset, value) {
        view.setUint32(offset, value, true);
    }

    function concatBytes(parts) {
        const size = parts.reduce((sum, part) => sum + part.length, 0);
        const out = new Uint8Array(size);
        let offset = 0;
        parts.forEach(part => {
            out.set(part, offset);
            offset += part.length;
        });
        return out;
    }

    function encodeUtf8(text) {
        if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(text);
        return Uint8Array.from(Buffer.from(text, 'utf8'));
    }

    // 存储法（method 0）的 zip。Excel 和 openpyxl 都能读，不需要压缩库。
    function zipStore(files) {
        const encoderParts = [];
        const central = [];
        let offset = 0;
        files.forEach(file => {
            const name = encodeUtf8(file.name);
            const data = file.data;
            const crc = crc32(data);
            const local = new Uint8Array(30 + name.length);
            const view = new DataView(local.buffer);
            u32(view, 0, 0x04034b50);
            u16(view, 4, 20);
            u16(view, 8, 0);
            u32(view, 14, crc);
            u32(view, 18, data.length);
            u32(view, 22, data.length);
            u16(view, 26, name.length);
            local.set(name, 30);
            encoderParts.push(local, data);
            const cen = new Uint8Array(46 + name.length);
            const cenView = new DataView(cen.buffer);
            u32(cenView, 0, 0x02014b50);
            u16(cenView, 4, 20);
            u16(cenView, 6, 20);
            u32(cenView, 16, crc);
            u32(cenView, 20, data.length);
            u32(cenView, 24, data.length);
            u16(cenView, 28, name.length);
            u32(cenView, 42, offset);
            cen.set(name, 46);
            central.push(cen);
            offset += local.length + data.length;
        });
        const centralBytes = concatBytes(central);
        const end = new Uint8Array(22);
        const endView = new DataView(end.buffer);
        u32(endView, 0, 0x06054b50);
        u16(endView, 8, files.length);
        u16(endView, 10, files.length);
        u32(endView, 12, centralBytes.length);
        u32(endView, 16, offset);
        return concatBytes(encoderParts.concat([centralBytes, end]));
    }

    function buildXlsxBytes(options) {
        const headers = options.headers || [];
        const types = options.types || [];
        const dataRows = options.rows || [];
        const headerRow = headers.map(header => ({ kind: 'text', value: String(header) }));
        const body = dataRows.map(row => headers.map((_, index) => normalizeCell(row[index], types[index] || 'text')));
        const scopeRows = options.scopeRows || [];
        const scopeHeader = [{ kind: 'text', value: '项目' }, { kind: 'text', value: '内容' }];
        const scopeBody = scopeRows.map(pair => [
            { kind: 'text', value: String(pair[0]) },
            normalizeCell(pair[1], pair[2] || 'text')
        ]);
        const files = [
            { name: '[Content_Types].xml', data: encodeUtf8(contentTypesXml()) },
            { name: '_rels/.rels', data: encodeUtf8(rootRels()) },
            { name: 'xl/workbook.xml', data: encodeUtf8(workbookXml()) },
            { name: 'xl/_rels/workbook.xml.rels', data: encodeUtf8(workbookRels()) },
            { name: 'xl/styles.xml', data: encodeUtf8(stylesXml()) },
            { name: 'xl/worksheets/sheet1.xml', data: encodeUtf8(sheetXml([headerRow].concat(body))) },
            { name: 'xl/worksheets/sheet2.xml', data: encodeUtf8(sheetXml([scopeHeader].concat(scopeBody))) }
        ];
        return zipStore(files);
    }

    function exportableColumns(spec, order) {
        const byKey = new Map((spec.columns || []).map(col => [col.key, col]));
        return order.map(key => byKey.get(key)).filter(col => col && col.export !== false);
    }

    function scopePairs(spec, composed, columns) {
        const now = new Date();
        const stamp = `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())} ${pad2(now.getHours())}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())}`;
        return [
            ['表格', spec.title || spec.id, 'text'],
            ['导出时间', stamp, 'datetime'],
            ['筛选', composed.raw.filterText || '无', 'text'],
            ['排序', composed.raw.sortText || '无', 'text'],
            ['列顺序', columns.map(col => col.label).join('、'), 'text'],
            ['导出行数', composed.count, 'number'],
            ['是否只含已加载的部分数据', composed.partial ? '是' : '否', 'text'],
            ['页面说明', composed.text, 'text'],
            ['文件格式', 'Office Open XML 工作簿（.xlsx），不是把 CSV 改成 .xlsx 后缀。', 'text'],
            ['去重', '按行原样写入，不按单元格内容合并或去重。', 'text']
        ];
    }

    function safeFilename(title) {
        const cleaned = String(title || '表格').replace(/[\\/:*?"<>|]/g, '_').replace(/\s+/g, ' ').trim() || '表格';
        const now = new Date();
        const stamp = `${now.getFullYear()}${pad2(now.getMonth() + 1)}${pad2(now.getDate())}-${pad2(now.getHours())}${pad2(now.getMinutes())}${pad2(now.getSeconds())}`;
        return `${cleaned}_${stamp}.xlsx`;
    }

    function exportSpec(spec) {
        const order = resolvedOrder(spec);
        const columns = exportableColumns(spec, order);
        const rows = (spec.rows || []).map(row => columns.map(col => row ? row[col.key] : ''));
        const composed = composeScope(spec);
        return {
            filename: safeFilename(spec.title || spec.id),
            bytes: buildXlsxBytes({
                headers: columns.map(col => col.label),
                types: columns.map(col => col.type || 'text'),
                rows,
                scopeRows: scopePairs(spec, composed, columns)
            }),
            headers: columns.map(col => col.label),
            rowCount: rows.length
        };
    }

    function downloadBytes(filename, bytes) {
        const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1500);
    }

    function findStage(id) {
        if (typeof document === 'undefined') return null;
        return Array.from(document.querySelectorAll('.table-stage')).find(el => el.dataset.tableId === id) || null;
    }

    function barHtml() {
        return `<div class="table-stage-bar">` +
            `<div class="table-stage-heading">` +
            `<div class="table-stage-title" role="heading" aria-level="2"></div>` +
            `<div class="table-stage-scope"></div>` +
            `</div>` +
            `<div class="table-stage-actions">` +
            `<button type="button" class="btn btn-sm" data-stage-action="columns">列顺序</button>` +
            `<button type="button" class="btn btn-sm btn-export" data-stage-action="export">导出Excel</button>` +
            `<button type="button" class="btn btn-sm" data-stage-action="fullscreen">全屏</button>` +
            `</div></div>`;
    }

    function ensureBar(stage) {
        if (!stage.querySelector('.table-stage-bar')) {
            stage.insertAdjacentHTML('afterbegin', barHtml());
        }
    }

    function ensureScroll(stage) {
        if (stage.querySelector('.table-stage-scroll')) return;
        const table = stage.querySelector('table');
        if (!table) return;
        if (table.parentElement === stage) {
            const wrap = document.createElement('div');
            wrap.className = 'table-stage-scroll';
            stage.insertBefore(wrap, table);
            wrap.appendChild(table);
            return;
        }
        table.parentElement.classList.add('table-stage-scroll');
    }

    function ensureDataCols(table, columns) {
        const head = table.tHead && table.tHead.rows[0];
        if (!head) return;
        Array.from(head.cells).forEach((th, index) => {
            if (!th.dataset.col && columns[index]) th.dataset.col = columns[index].key;
        });
        Array.from(table.tBodies || []).forEach(tbody => {
            Array.from(tbody.rows).forEach(tr => {
                const cells = Array.from(tr.cells);
                if (cells.length === 1 && cells[0].colSpan > 1) {
                    cells[0].colSpan = columns.length || 1;
                    return;
                }
                if (cells.some(td => td.dataset.col)) return;
                if (cells.length !== columns.length) {
                    if (typeof console !== 'undefined') console.warn('表格列数和数据列定义不一致', columns.length, cells.length);
                    return;
                }
                cells.forEach((td, index) => {
                    td.dataset.col = columns[index].key;
                });
            });
        });
    }

    function reorderRow(row, order) {
        const cells = Array.from(row.cells).filter(cell => !(cell.colSpan > 1 && row.cells.length === 1));
        if (!cells.length || cells.length !== row.cells.length) return;
        const map = new Map(cells.map(cell => [cell.dataset.col, cell]));
        const ordered = [];
        order.forEach(key => {
            const cell = map.get(key);
            if (cell) ordered.push(cell);
        });
        cells.forEach(cell => {
            if (ordered.indexOf(cell) === -1) ordered.push(cell);
        });
        ordered.forEach(cell => row.appendChild(cell));
    }

    function ensureGrips(table) {
        const head = table.tHead && table.tHead.rows[0];
        if (!head) return;
        Array.from(head.cells).forEach(th => {
            if (!th.dataset.col || th.querySelector('.col-drag')) return;
            const grip = document.createElement('span');
            grip.className = 'col-drag';
            grip.draggable = true;
            grip.title = '拖动调整列顺序，不会改变行的排序';
            grip.setAttribute('aria-hidden', 'true');
            grip.textContent = '⋮⋮';
            th.insertBefore(grip, th.firstChild);
        });
    }

    function syncPinnedActions(table, order) {
        const last = order[order.length - 1];
        table.querySelectorAll('th.col-actions, td.user-actions').forEach(cell => {
            cell.classList.toggle('col-actions-unpinned', !!cell.dataset.col && cell.dataset.col !== last);
        });
    }

    function isFullscreen(stage) {
        return stage.classList.contains('table-stage-fallback-fs') ||
            (typeof document !== 'undefined' && document.fullscreenElement === stage);
    }

    function syncFullscreenButton(stage) {
        const button = stage.querySelector('[data-stage-action="fullscreen"]');
        if (!button) return;
        const on = isFullscreen(stage);
        button.textContent = on ? '退出全屏' : '全屏';
        button.setAttribute('aria-pressed', on ? 'true' : 'false');
    }

    function updateStageText(stage, spec) {
        const composed = composeScope(spec);
        const title = stage.querySelector('.table-stage-title');
        const scope = stage.querySelector('.table-stage-scope');
        if (title) title.textContent = spec.title || spec.id;
        if (scope) {
            scope.textContent = composed.text;
            scope.classList.toggle('is-partial', composed.partial);
        }
        const columnsBtn = stage.querySelector('[data-stage-action="columns"]');
        if (columnsBtn && !columnsBtn.dataset.open) columnsBtn.textContent = isCustomOrder(spec) ? '列顺序*' : '列顺序';
        const exportBtn = stage.querySelector('[data-stage-action="export"]');
        if (exportBtn) {
            exportBtn.title = composed.partial
                ? composed.text
                : `导出当前筛选条件下的全部 ${composed.count} 条，包含屏幕外的行`;
        }
        syncFullscreenButton(stage);
    }

    function finish(id) {
        const spec = registry[id];
        const stage = findStage(id);
        if (!spec || !stage || typeof document === 'undefined') return;
        ensureBar(stage);
        ensureScroll(stage);
        const table = stage.querySelector('table');
        if (!table) {
            updateStageText(stage, spec);
            return;
        }
        const columns = spec.columns || [];
        ensureDataCols(table, columns);
        const order = resolvedOrder(spec);
        const head = table.tHead && table.tHead.rows[0];
        if (head) reorderRow(head, order);
        Array.from(table.tBodies || []).forEach(tbody => {
            Array.from(tbody.rows).forEach(tr => reorderRow(tr, order));
        });
        ensureGrips(table);
        syncPinnedActions(table, order);
        updateStageText(stage, spec);
        const panel = stage.querySelector('.col-order-pop');
        if (panel && !panel.hidden) renderColumnPanel(stage, id);
    }

    function finishWithin(root) {
        if (!root) return;
        root.querySelectorAll('.table-stage[data-table-id]').forEach(stage => finish(stage.dataset.tableId));
    }

    function renderColumnPanel(stage, id) {
        const spec = registry[id];
        if (!spec) return;
        let panel = stage.querySelector('.col-order-pop');
        if (!panel) {
            panel = document.createElement('div');
            panel.className = 'col-order-pop';
            const actions = stage.querySelector('.table-stage-actions') || stage;
            actions.appendChild(panel);
        }
        const order = resolvedOrder(spec);
        const byKey = new Map((spec.columns || []).map(col => [col.key, col]));
        const items = order.map(key => {
            const col = byKey.get(key);
            const label = col ? col.label : key;
            return `<li class="col-order-item">` +
                `<span>${xmlText(label)}</span>` +
                `<button type="button" class="btn btn-sm" data-stage-action="move-column" data-col="${xmlAttr(key)}" data-dir="-1">上移</button>` +
                `<button type="button" class="btn btn-sm" data-stage-action="move-column" data-col="${xmlAttr(key)}" data-dir="1">下移</button>` +
                `</li>`;
        }).join('');
        panel.innerHTML = `<div class="col-order-title">调整列顺序</div>` +
            `<p class="col-order-hint">上下移动或拖动表头左侧的手柄。移动的是列，不是给行排序；行排序仍用表头上的文字。</p>` +
            `<ul class="col-order-list">${items}</ul>` +
            `<div class="col-order-footer"><button type="button" class="btn btn-sm" data-stage-action="reset-columns">恢复默认</button></div>`;
        panel.hidden = false;
    }

    function toggleColumnPanel(stage, id) {
        const existing = stage.querySelector('.col-order-pop');
        if (existing && !existing.hidden) {
            existing.hidden = true;
            return;
        }
        document.querySelectorAll('.col-order-pop').forEach(panel => { panel.hidden = true; });
        renderColumnPanel(stage, id);
    }

    function moveColumn(id, key, dir) {
        const spec = registry[id];
        if (!spec) return;
        const order = resolvedOrder(spec).slice();
        const from = order.indexOf(key);
        const to = from + dir;
        if (from < 0 || to < 0 || to >= order.length) return;
        const item = order.splice(from, 1)[0];
        order.splice(to, 0, item);
        saveOrder(id, order);
        finish(id);
    }

    function moveColumnTo(id, key, targetKey) {
        const spec = registry[id];
        if (!spec || !key || key === targetKey) return;
        const order = resolvedOrder(spec).slice();
        const from = order.indexOf(key);
        const to = order.indexOf(targetKey);
        if (from < 0 || to < 0) return;
        const item = order.splice(from, 1)[0];
        order.splice(to, 0, item);
        saveOrder(id, order);
        finish(id);
    }

    function resetColumns(id) {
        clearOrder(id);
        finish(id);
    }

    function exportTable(id) {
        const spec = registry[id];
        if (!spec) return null;
        const result = exportSpec(spec);
        if (typeof document !== 'undefined') downloadBytes(result.filename, result.bytes);
        return result;
    }

    function enterFallback(stage) {
        stage.classList.add('table-stage-fallback-fs');
        document.body.classList.add('table-fs-lock');
        syncFullscreenButton(stage);
    }

    function exitFallback(stage) {
        stage.classList.remove('table-stage-fallback-fs');
        if (!document.querySelector('.table-stage-fallback-fs')) document.body.classList.remove('table-fs-lock');
        syncFullscreenButton(stage);
    }

    async function toggleFullscreen(stage) {
        if (isFullscreen(stage)) {
            if (stage.classList.contains('table-stage-fallback-fs')) exitFallback(stage);
            if (document.fullscreenElement === stage && document.exitFullscreen) {
                try { await document.exitFullscreen(); } catch (e) { /* 浏览器拒绝时兜底已经退出 */ }
            }
            syncFullscreenButton(stage);
            return;
        }
        const request = stage.requestFullscreen || stage.webkitRequestFullscreen;
        if (!request) {
            enterFallback(stage);
            return;
        }
        try {
            await request.call(stage);
            if (document.fullscreenElement !== stage) enterFallback(stage);
        } catch (e) {
            enterFallback(stage);
        }
        syncFullscreenButton(stage);
    }

    let dragCol = '';
    let dragTableId = '';

    function clearDragStyles() {
        if (typeof document === 'undefined') return;
        document.querySelectorAll('.col-dragging, .col-drop-target').forEach(el => {
            el.classList.remove('col-dragging');
            el.classList.remove('col-drop-target');
        });
        dragCol = '';
        dragTableId = '';
    }

    function bindEvents() {
        document.addEventListener('click', event => {
            const grip = event.target.closest && event.target.closest('.col-drag');
            if (grip) {
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            const actionEl = event.target.closest && event.target.closest('[data-stage-action]');
            if (actionEl) {
                const stage = actionEl.closest('.table-stage');
                if (!stage) return;
                const id = stage.dataset.tableId;
                const action = actionEl.dataset.stageAction;
                event.preventDefault();
                if (action === 'export') exportTable(id);
                else if (action === 'fullscreen') toggleFullscreen(stage);
                else if (action === 'columns') toggleColumnPanel(stage, id);
                else if (action === 'reset-columns') resetColumns(id);
                else if (action === 'move-column') moveColumn(id, actionEl.dataset.col, Number(actionEl.dataset.dir));
                return;
            }
            if (!(event.target.closest && event.target.closest('.col-order-pop'))) {
                document.querySelectorAll('.col-order-pop').forEach(panel => { panel.hidden = true; });
            }
        }, true);

        document.addEventListener('dragstart', event => {
            const grip = event.target.closest && event.target.closest('.col-drag');
            if (!grip) return;
            const th = grip.closest('th');
            const stage = grip.closest('.table-stage');
            dragCol = th && th.dataset.col || '';
            dragTableId = stage && stage.dataset.tableId || '';
            if (!dragCol) return;
            event.dataTransfer.effectAllowed = 'move';
            try { event.dataTransfer.setData('text/plain', dragCol); } catch (e) { /* 个别浏览器在 dragstart 拒绝 setData */ }
            th.classList.add('col-dragging');
            event.stopPropagation();
        });

        document.addEventListener('dragover', event => {
            if (!dragCol) return;
            const th = event.target.closest && event.target.closest('th[data-col]');
            if (!th || th.closest('.table-stage') && th.closest('.table-stage').dataset.tableId !== dragTableId) return;
            event.preventDefault();
            th.classList.add('col-drop-target');
        });

        document.addEventListener('dragleave', event => {
            const th = event.target.closest && event.target.closest('th');
            if (th) th.classList.remove('col-drop-target');
        });

        document.addEventListener('drop', event => {
            const th = event.target.closest && event.target.closest('th[data-col]');
            if (!th || !dragCol || !dragTableId) return;
            event.preventDefault();
            moveColumnTo(dragTableId, dragCol, th.dataset.col);
            clearDragStyles();
        });

        document.addEventListener('dragend', clearDragStyles);

        document.addEventListener('keydown', event => {
            if (event.key !== 'Escape') return;
            const fallback = document.querySelector('.table-stage-fallback-fs');
            if (fallback) {
                exitFallback(fallback);
                const panel = fallback.querySelector('.col-order-pop');
                if (panel) panel.hidden = true;
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            if (document.fullscreenElement && document.fullscreenElement.classList &&
                document.fullscreenElement.classList.contains('table-stage')) {
                const panel = document.fullscreenElement.querySelector('.col-order-pop');
                if (panel) panel.hidden = true;
                return;
            }
            document.querySelectorAll('.col-order-pop').forEach(panel => { panel.hidden = true; });
        });

        document.addEventListener('fullscreenchange', () => {
            document.querySelectorAll('.table-stage').forEach(syncFullscreenButton);
        });
    }

    if (typeof document !== 'undefined') bindEvents();

    return {
        resolveColumnOrder,
        storageKey,
        loadOrder,
        saveOrder,
        clearOrder,
        register,
        setRows,
        getSpec,
        composeScope,
        normalizeCell,
        buildXlsxBytes,
        exportSpec,
        finish,
        finishWithin,
        exportTable,
        resetColumns,
        moveColumn,
        resolvedOrder: id => registry[id] ? resolvedOrder(registry[id]) : []
    };
});
