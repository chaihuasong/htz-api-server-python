/**
 * 用隔离库里的模拟数据打开管理后台，检查饼图已删除、列顺序、导出和全屏。
 * 运行：NODE_PATH=/tmp/node_modules node tests/browser_admin_tables.mjs
 * 需要本机 Chrome 和已经在 127.0.0.1:8765 上、用隔离库启动的服务。
 */
import fs from 'fs';
import path from 'path';
import { spawnSync } from 'child_process';
import { createRequire } from 'module';

const require = createRequire('/tmp/node_modules/puppeteer-core/package.json');
const puppeteer = require('puppeteer-core');

const downloadDir = '/tmp/htz-admin-downloads';
const shotDir = '/opt/cursor/artifacts';
fs.mkdirSync(downloadDir, { recursive: true });
fs.mkdirSync(shotDir, { recursive: true });
for (const name of fs.readdirSync(downloadDir)) fs.unlinkSync(path.join(downloadDir, name));

const errors = [];
function check(cond, message) {
    if (!cond) errors.push(message);
}

const browser = await puppeteer.launch({
    executablePath: '/usr/local/bin/google-chrome',
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1440,1000'],
});
const page = await browser.newPage();
page.setDefaultTimeout(20000);
await page.setViewport({ width: 1440, height: 1000 });
const client = await page.createCDPSession();
await client.send('Browser.setDownloadBehavior', {
    behavior: 'allow',
    downloadPath: downloadDir,
    eventsEnabled: true,
});
page.on('console', msg => {
    const text = msg.text();
    if (text.includes('列数和数据列定义不一致')) errors.push('控制台列数不一致: ' + text);
});

async function shot(name) {
    await page.screenshot({ path: path.join(shotDir, name), fullPage: false });
}

async function exportTable(tableId) {
    const payload = await page.evaluate(id => {
        const button = document.querySelector(`[data-table-id="${id}"] [data-stage-action="export"]`);
        if (!button) return { error: '没有导出按钮' };
        let blobSize = 0;
        const orig = URL.createObjectURL;
        URL.createObjectURL = blob => {
            blobSize = blob && blob.size || 0;
            return orig.call(URL, blob);
        };
        button.click();
        URL.createObjectURL = orig;
        const result = AdminTables.exportTable(id);
        let binary = '';
        const bytes = result.bytes;
        const chunk = 0x8000;
        for (let i = 0; i < bytes.length; i += chunk) {
            binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
        }
        return { filename: result.filename, blobSize, b64: btoa(binary) };
    }, tableId);
    if (payload.error) throw new Error(payload.error + ': ' + tableId);
    if (!payload.blobSize) throw new Error('点击导出没有生成 xlsx 文件: ' + tableId);
    if (!payload.filename.endsWith('.xlsx')) throw new Error('导出文件名不是 xlsx: ' + payload.filename);
    const file = path.join(downloadDir, tableId + '.xlsx');
    fs.writeFileSync(file, Buffer.from(payload.b64, 'base64'));
    return file;
}

function readXlsx(file) {
    const py = `
import json, sys
import openpyxl
wb = openpyxl.load_workbook(sys.argv[1])
data = wb['数据']
scope = {row[0].value: row[1].value for row in wb['导出说明'].iter_rows(min_row=2)}
rows = []
for row in data.iter_rows(min_row=2, values_only=True):
    rows.append(["" if v is None else v for v in row])
print(json.dumps({
  "sheets": wb.sheetnames,
  "headers": [c.value for c in data[1]],
  "rows": rows,
  "scope": {k: ("" if v is None else str(v)) for k, v in scope.items()},
}, ensure_ascii=False, default=str))
`;
    const result = spawnSync('python3', ['-c', py, file], { encoding: 'utf8' });
    if (result.status !== 0) throw new Error(result.stderr || result.stdout);
    return JSON.parse(result.stdout);
}

try {
    await page.goto('http://127.0.0.1:8765/admin', { waitUntil: 'domcontentloaded' });
    await page.type('#login-username', 'admin');
    await page.type('#login-password', 'isolate-pass');
    await Promise.all([
        page.waitForResponse(res => res.url().includes('/usage/summary') && res.status() === 200),
        page.click('.btn-login'),
    ]);
    await page.waitForSelector('[data-table-id="usage-source"] .table-stage-title');
    await page.waitForFunction(() => document.querySelectorAll('#usage-chart .bar').length > 0);

    const usage = await page.evaluate(() => ({
        donut: document.querySelectorAll('.donut-card, .donut-svg, #usage-donuts, .donut-grid-inner').length,
        bars: document.querySelectorAll('#usage-chart .bar').length,
        stats: document.querySelectorAll('#usage-stats-grid .stat-card').length,
        titles: [...document.querySelectorAll('#usage-panel .table-stage-title')].map(el => el.textContent),
        sourceText: document.querySelector('[data-table-id="usage-source"] tbody').innerText,
        usagePartial: document.querySelector('[data-table-id="usage"] .table-stage-scope').classList.contains('is-partial'),
        usageScope: document.querySelector('[data-table-id="usage"] .table-stage-scope').textContent,
    }));
    check(usage.donut === 0, '用量页仍有饼图/环形图');
    check(usage.bars > 0, '柱状图被删掉了');
    check(usage.stats === 8, '统计卡片数量不对: ' + usage.stats);
    check(usage.titles.includes('来源分布'), '缺少来源分布标题');
    check(usage.titles.includes('每日设备数（最近30天）'), '缺少每日设备数标题');
    check(usage.titles.includes('用量详细记录'), '缺少用量详细记录标题');
    check(usage.titles.includes('营销手机型号分布'), '缺少机型分布标题');
    check(usage.sourceText.includes('来源&<测试>'), '来源表没有特殊字符来源: ' + usage.sourceText);
    check(usage.usagePartial, '用量明细没有标明接口上限');
    check(usage.usageScope.includes('1000'), '用量范围没有写 1000 条上限');
    check(usage.usageScope.includes('不是只导出当前屏幕'), '用量范围没有说明不是只导出屏幕');
    await shot('admin-usage-no-pie.png');

    await page.evaluate(() => document.querySelector('.tab[onclick*="users"]').click());
    await page.waitForFunction(() => document.querySelectorAll('#users-table tr').length >= 2);
    await page.evaluate(() => document.querySelector('[data-table-id="users"] [data-stage-action="columns"]').click());
    await page.waitForSelector('[data-table-id="users"] .col-order-pop');
    const hint = await page.$eval('[data-table-id="users"] .col-order-hint', el => el.textContent);
    check(hint.includes('不是给行排序'), '列顺序说明没有和行排序区分开');
    await shot('admin-column-order-panel.png');
    for (let i = 0; i < 2; i++) {
        await page.evaluate(() => {
            const item = [...document.querySelectorAll('[data-table-id="users"] .col-order-item')]
                .find(li => li.querySelector('span').textContent === '昵称');
            item.querySelector('[data-dir="-1"]').click();
        });
    }
    const moved = await page.evaluate(() => {
        const table = document.querySelector('[data-table-id="users"] table');
        const headers = [...table.tHead.rows[0].cells].map(cell => cell.dataset.col);
        const first = [...table.tBodies[0].rows[0].cells].map(cell => cell.dataset.col);
        return { headers, first, text: table.tBodies[0].rows[0].cells[0].innerText, second: table.tBodies[0].rows[0].cells[1].innerText };
    });
    check(moved.headers[0] === 'nickname' && moved.headers[1] === 'id', '表头没有按列顺序移动: ' + moved.headers.join(','));
    check(moved.first[0] === 'nickname' && moved.first[1] === 'id', '单元格没有和表头一起移动: ' + moved.first.join(','));
    check(moved.text.includes('隔离测试-张三'), '第一列不是昵称内容: ' + moved.text);
    check(String(moved.second || '').trim() !== '' && !String(moved.second).includes('隔离测试'), '第二列仍是昵称，没有跟着表头换成 ID: ' + moved.second);
    await shot('admin-users-reordered.png');

    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForSelector('[data-table-id="usage"] .table-stage-title');
    await page.evaluate(() => document.querySelector('.tab[onclick*="users"]').click());
    await page.waitForFunction(() => document.querySelectorAll('#users-table tr').length >= 2);
    const persisted = await page.evaluate(() => [...document.querySelector('[data-table-id="users"] table').tHead.rows[0].cells].map(cell => cell.dataset.col));
    check(persisted[0] === 'nickname', '刷新后列顺序没有记住: ' + persisted.join(','));

    await page.evaluate(() => {
        document.querySelector('[data-table-id="users"] [data-stage-action="columns"]').click();
    });
    await page.waitForSelector('[data-table-id="users"] [data-stage-action="reset-columns"]');
    await page.evaluate(() => document.querySelector('[data-table-id="users"] [data-stage-action="reset-columns"]').click());
    const reset = await page.evaluate(() => [...document.querySelector('[data-table-id="users"] table').tHead.rows[0].cells].map(cell => cell.dataset.col)[0]);
    check(reset === 'id', '恢复默认后第一列不是 ID: ' + reset);

    await page.evaluate(() => {
        document.querySelector('#user-search').value = '没有这个人zzz';
        filterUsers();
    });
    const emptyFile = await exportTable('users');
    const emptyBook = readXlsx(emptyFile);
    check(emptyBook.headers[0] === 'ID', '空筛选导出表头不对: ' + emptyBook.headers.join(','));
    check(emptyBook.rows.length === 0, '空筛选被导出成了全部用户: ' + emptyBook.rows.length);
    check(emptyBook.scope['导出行数'] === '0', '空表导出行数不是 0');
    check(emptyBook.scope['页面说明'].includes('共 0 条'), '页面说明没有写 0 条');

    await page.evaluate(() => {
        document.querySelector('#user-search').value = '备注<特殊>';
        filterUsers();
    });
    const oneFile = await exportTable('users');
    const oneBook = readXlsx(oneFile);
    check(oneBook.rows.length === 1, '筛选后应该只有 1 行，实际 ' + oneBook.rows.length);
    check(oneBook.rows[0].join('\n').includes('备注<特殊>&'), '特殊字符备注没有进 Excel');
    check(oneBook.scope['页面说明'].includes('不是只导出当前屏幕'), '用户导出范围说明不对');
    check(!oneBook.headers.includes('操作'), '操作列被导出了');

    await page.evaluate(() => document.querySelector('.tab[onclick*="feedback"]').click());
    await page.waitForFunction(() => document.querySelectorAll('#feedback-table tr').length >= 2);
    const feedbackFile = await exportTable('feedback');
    const feedbackBook = readXlsx(feedbackFile);
    check(feedbackBook.rows.length === 2, '两条内容相同的反馈被去重了: ' + feedbackBook.rows.length);
    check(feedbackBook.rows.every(row => row.join('\n').includes("同样的内容 <>&\"'=1+1")), '反馈特殊字符丢失');
    check(feedbackBook.scope['页面说明'].includes('1000'), '反馈没有说明 1000 条上限');

    await page.evaluate(() => document.querySelector('.tab[onclick*="usage"]').click());
    await page.waitForSelector('[data-table-id="usage"] tbody tr');
    const usageFile = await exportTable('usage');
    const usageBook = readXlsx(usageFile);
    check(usageBook.rows.length === 3, '用量导出行数不是 3: ' + usageBook.rows.length);
    check(usageBook.headers.includes('设备ID'), '用量表头不对');
    check(usageBook.rows.some(row => row.includes('iso-device-1')), '用量导出缺设备');
    check(usageBook.rows.some(row => row.includes('iso-device-2')), '空来源的另一条用量被丢掉了');
    check(usageBook.rows.filter(row => row.includes('iso-device-1')).length === 2, '同一设备的不同日期被合并了');
    const dateIndex = usageBook.headers.indexOf('日期');
    check(String(usageBook.rows[0][dateIndex]).startsWith('2026-11-10'), '导出没有按当前日期降序: ' + usageBook.rows.map(row => row[dateIndex]).join(','));
    check(String(usageBook.rows[2][dateIndex]).startsWith('2026-11-08'), '日期升序被写反了: ' + usageBook.rows.map(row => row[dateIndex]).join(','));

    await page.evaluate(() => document.querySelector('.tab[onclick*="logs"]').click());
    await page.waitForFunction(() => (document.querySelector('#logs-table') || {}).innerText && document.querySelector('#logs-table').innerText.includes('ISOLATED_LOG_HEAD'));
    const logFile = await exportTable('logs');
    const logBook = readXlsx(logFile);
    const info = logBook.rows.map(row => row.join('\n')).join('\n');
    check(info.includes('ISOLATED_LOG_HEAD <&>'), '日志特殊字符丢失');
    check(!info.includes('X'.repeat(520)), '日志导出把被接口截断的后半段也写进去了');
    check(logBook.scope['页面说明'].includes('500'), '日志没有说明 500 条/500 字上限');

    await page.evaluate(() => document.querySelector('.tab[onclick*="files"]').click());
    await page.waitForSelector('[data-table-id="files"] .table-stage-title');
    const filesFile = await exportTable('files');
    const filesBook = readXlsx(filesFile);
    check(filesBook.headers.join(',') === '预览,文件名,大小,时间,地址', '空文件表表头不对: ' + filesBook.headers.join(','));
    check(filesBook.rows.length === 0, '空文件表导出了行');

    await page.evaluate(() => document.querySelector('.tab[onclick*="switchTab(\'usage\')"]').click());
    await page.waitForSelector('#usage-panel.active [data-table-id="usage"] .table-stage-title');
    await page.evaluate(() => {
        const stage = document.querySelector('[data-table-id="usage"]');
        stage.requestFullscreen = () => Promise.reject(new Error('fullscreen unavailable'));
        delete stage.webkitRequestFullscreen;
        stage.querySelector('[data-stage-action="fullscreen"]').click();
    });
    await page.waitForSelector('[data-table-id="usage"].table-stage-fallback-fs .table-stage-title');
    const fs = await page.evaluate(() => {
        const stage = document.querySelector('[data-table-id="usage"].table-stage-fallback-fs');
        const rect = stage.getBoundingClientRect();
        return {
            title: stage.querySelector('.table-stage-title').textContent,
            scope: stage.querySelector('.table-stage-scope').textContent,
            button: stage.querySelector('[data-stage-action="fullscreen"]').textContent,
            hasTable: !!stage.querySelector('tbody tr'),
            width: rect.width,
            height: rect.height,
        };
    });
    check(fs.width > 800 && fs.height > 500, '全屏区域没有铺开: ' + fs.width + 'x' + fs.height);
    check(fs.title === '用量详细记录', '全屏标题不对: ' + fs.title);
    check(fs.scope.includes('筛选：') && fs.scope.includes('共 '), '全屏没有筛选范围: ' + fs.scope);
    check(fs.button === '退出全屏', '全屏按钮没有变成退出');
    check(fs.hasTable, '全屏里没有表格');
    await shot('admin-usage-fullscreen.png');
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('.table-stage-fallback-fs'));
    const afterEsc = await page.evaluate(() => document.querySelector('[data-table-id="usage"] [data-stage-action="fullscreen"]').textContent);
    check(afterEsc === '全屏', 'Escape 没有退出全屏');

    await page.evaluate(() => document.querySelector('#usage-table .link-cell').click());
    await page.waitForSelector('#usage-detail-modal.show .table-stage-title');
    const modalTitles = await page.$$eval('#usage-detail-body .table-stage-title', els => els.map(el => el.textContent));
    check(modalTitles.includes('设备用量 · 登录过的账号'), '设备明细缺少账号表: ' + modalTitles.join(','));
    check(modalTitles.includes('设备用量 · 按天明细'), '设备明细缺少按天表: ' + modalTitles.join(','));
    const deviceUsers = readXlsx(await exportTable('usage-device-users'));
    check(deviceUsers.rows.length >= 1, '设备账号表没有导出已加载的全部行');
    check(deviceUsers.scope['页面说明'].includes('没有分页'), '明细导出没有说明接口没有分页');
    await shot('admin-usage-detail.png');
    await page.evaluate(() => document.querySelector('#usage-detail-modal .modal-footer .btn').click());

    const titles = await page.evaluate(() => [...document.querySelectorAll('.table-stage-title')].map(el => el.textContent));
    const expected = ['意见反馈', '系统通知', '文件', 'AK/SK 管理', '用户信息', '日志信息', '机型映射', '来源分布', '每日设备数（最近30天）', '用量详细记录', '营销手机型号分布'];
    expected.forEach(title => check(titles.includes(title), '页面上缺少表格标题: ' + title));
} finally {
    await browser.close();
}

if (errors.length) {
    console.error(errors.map(item => '- ' + item).join('\n'));
    process.exit(1);
}
console.log('browser checks passed');
