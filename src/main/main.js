const { app, BrowserWindow, ipcMain, shell, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { createProtocol } = require('../protocol');

// 修复：Windows 上残留"僵尸 SID"导致 GPU 进程沙箱崩溃（electron#51761），退出码 0x80000003
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('disable-gpu');

// ---- 诊断日志（沙箱无法显示 GUI，写文件便于定位启动问题）----
const LOG = app.isPackaged ? path.join(app.getPath('userData'), 'airfloat.log') : path.join(__dirname, '..', '..', 'airfloat.log');
function log(msg) {
  try { fs.appendFileSync(LOG, new Date().toISOString() + '  ' + msg + '\n'); } catch (e) {}
}
log('main.js 已加载, typeof app=' + typeof app + ', typeof ipcMain=' + typeof ipcMain);
process.on('uncaughtException', (err) => log('未捕获异常: ' + (err && err.stack ? err.stack : err)));
process.on('unhandledRejection', (err) => log('未处理 Promise 拒绝: ' + (err && err.stack ? err.stack : err)));

let win = null;
let proto = null;
let cfg = { alias: '我的电脑', enabled: true, receiveMode: 'everyone', whitelist: [] };
const peers = new Map(); // fingerprint -> peer

const configPath = () => path.join(app.getPath('userData'), 'config.json');
const cacheDir = () => path.join(app.getPath('userData'), 'cache');

function loadConfig() {
  try { cfg = Object.assign(cfg, JSON.parse(fs.readFileSync(configPath(), 'utf8'))); } catch {}
}
function saveConfig() { fs.writeFileSync(configPath(), JSON.stringify(cfg, null, 2)); }

function localIp() {
  const ifs = os.networkInterfaces();
  for (const name of Object.keys(ifs)) {
    for (const i of ifs[name]) if (i.family === 'IPv4' && !i.internal) return i.address;
  }
  return '127.0.0.1';
}

function state() {
  return {
    enabled: cfg.enabled,
    receiveMode: cfg.receiveMode,
    alias: cfg.alias,
    fingerprint: proto ? proto.getSelf().fingerprint : '',
    ip: localIp(),
    port: proto ? proto.getSelf().port : 53317,
  };
}

function deviceList() {
  return [...peers.values()].map((p) => ({ alias: p.alias, fingerprint: p.fingerprint, deviceType: p.deviceType, ip: p.ip }));
}

function broadcast(ev) { if (win) win.webContents.send('airfloat:event', ev); }

async function startProtocol() {
  log('startProtocol 开始');
  fs.mkdirSync(cacheDir(), { recursive: true });
  proto = await createProtocol({
    alias: cfg.alias,
    deviceType: 'desktop',
    version: '2.0',
    port: 53317,
    protocol: 'https',
    download: true,
    cacheDir: cacheDir(),
    getReceiveMode: () => (cfg.enabled ? cfg.receiveMode : 'off'),
    isTrusted: (fp) => cfg.whitelist.includes(fp),
    onPeer: (p) => { peers.set(p.fingerprint, p); broadcast({ type: 'devices', devices: deviceList() }); },
    onPeerLost: (fp) => { peers.delete(fp); broadcast({ type: 'devices', devices: deviceList() }); },
    onReceived: (item) => broadcast({ type: 'received', item }),
    onProgress: (ev) => broadcast({ type: 'progress', ev }),
  });
  await proto.start();
  log('startProtocol 完成, fingerprint=' + proto.getSelf().fingerprint);
  broadcast({ type: 'state', state: state() });
}

function createWindow() {
  log('createWindow 开始');
  win = new BrowserWindow({
    width: 360, height: 500,
    frame: false,
    resizable: true,
    backgroundColor: '#EAF3FB',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
  win.on('closed', () => { log('窗口已关闭'); win = null; });
  win.webContents.on('did-finish-load', () => log('渲染进程加载完成'));
  win.webContents.on('did-fail-load', (_e, code, desc) => log('渲染进程加载失败: ' + code + ' ' + desc));
  log('createWindow 完成');
}

// IPC
ipcMain.handle('get-state', () => state());
ipcMain.handle('set-enabled', (e, v) => { cfg.enabled = !!v; saveConfig(); broadcast({ type: 'state', state: state() }); });
ipcMain.handle('set-receive-mode', (e, m) => { if (['everyone', 'contacts', 'off'].includes(m)) cfg.receiveMode = m; saveConfig(); broadcast({ type: 'state', state: state() }); });
ipcMain.handle('get-devices', () => deviceList());
ipcMain.handle('send-files', async (e, fingerprint, paths) => {
  const peer = peers.get(fingerprint);
  if (!peer) throw new Error('未找到目标设备，请先选中一个设备');
  await proto.send(peer, paths.map((p) => ({ path: p })));
});
ipcMain.handle('reveal-cache', () => shell.openPath(cacheDir()));
ipcMain.on('drag-out', (e, filePath) => {
  const icon = nativeImage.createFromPath(filePath).resize({ width: 64, height: 64 });
  e.sender.startDrag({ file: filePath, icon });
});

app.whenReady().then(async () => {
  log('whenReady 触发');
  loadConfig();
  try {
    await startProtocol();
  } catch (err) {
    log('协议启动失败: ' + (err && err.message ? err.message : err));
    console.error('[AirFloat] 协议启动失败:', err);
  }
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

// TODO(M6): 常驻托盘 + 全局快捷键唤出（需要图标文件）
app.on('window-all-closed', () => app.quit());
