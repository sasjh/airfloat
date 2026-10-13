'use strict';

// Receive side of the LocalSend v2 protocol: HTTP(S) server for register / prepare-upload / upload / cancel / info.

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const { normalizePeer } = require('./peer-store');
const { uuid } = require('./send');

const BASE = '/api/localsend/v2';

function sanitizeFileName(name) {
  const cleaned = String(name || '')
    .replace(/[\\/\x00-\x1f]/g, '')
    .replace(/^\.+$/, '');
  return cleaned || 'unnamed';
}

class ReceiveServer {
  constructor({ self, selfInfo, tlsOptions, cacheDir, getReceiveMode, isTrusted, onReceived, peerStore }) {
    this.self = self;
    this.selfInfo = selfInfo;
    this.tlsOptions = tlsOptions;
    this.cacheDir = cacheDir;
    this.getReceiveMode = typeof getReceiveMode === 'function' ? getReceiveMode : () => 'everyone';
    this.isTrusted = typeof isTrusted === 'function' ? isTrusted : () => false;
    this.onReceived = typeof onReceived === 'function' ? onReceived : () => {};
    this.peerStore = peerStore;
    this.sessions = new Map();
    this.reservedPaths = new Set();
    this.server = null;
    this.cleanupTimer = null;
  }

  async start() {
    fs.mkdirSync(this.cacheDir, { recursive: true });
    await new Promise((resolve, reject) => {
      const handler = (req, res) => this._handle(req, res);
      const server = this.tlsOptions
        ? https.createServer(this.tlsOptions, handler)
        : http.createServer(handler);
      server.on('error', reject);
      server.listen(this.self.port, '0.0.0.0', () => {
        this.server = server;
        resolve();
      });
    });
    this.cleanupTimer = setInterval(() => this._sweepSessions(), 60000);
  }

  async stop() {
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer);
      this.cleanupTimer = null;
    }
    if (this.server) {
      const s = this.server;
      this.server = null;
      await new Promise((resolve) => s.close(() => resolve()));
    }
  }

  _remoteIp(req) {
    return String(req.socket.remoteAddress || '').replace(/^::ffff:/, '');
  }

  _handle(req, res) {
    let url;
    try {
      url = new URL(req.url, 'http://localhost');
    } catch {
      return this._json(res, 400, {});
    }
    const p = url.pathname;

    if (p === `${BASE}/info` && req.method === 'GET') {
      return this._json(res, 200, this.selfInfo());
    }

    if (p === `${BASE}/register` && req.method === 'POST') {
      return this._readBody(req)
        .then((body) => {
          let obj = {};
          try { obj = JSON.parse(body.toString('utf8')); } catch {}
          if (obj && obj.fingerprint) {
            this.peerStore.upsert(normalizePeer(obj, this._remoteIp(req)));
          }
          return this._json(res, 200, this.selfInfo());
        })
        .catch(() => this._json(res, 400, {}));
    }

    if (p === `${BASE}/prepare-upload` && req.method === 'POST') {
      return this._readBody(req)
        .then((body) => this._prepareUpload(req, res, body))
        .catch(() => this._json(res, 500, {}));
    }

    if (p === `${BASE}/upload` && req.method === 'POST') {
      return this._upload(req, res, url);
    }

    if (p === `${BASE}/cancel` && req.method === 'POST') {
      const sessionId = url.searchParams.get('sessionId');
      if (sessionId) this.sessions.delete(sessionId);
      res.writeHead(200);
      return res.end();
    }

    res.writeHead(404);
    res.end();
  }

  _prepareUpload(req, res, body) {
    let obj;
    try {
      obj = JSON.parse(body.toString('utf8'));
    } catch {
      return this._json(res, 400, {});
    }
    if (!obj || typeof obj.files !== 'object' || obj.files === null) {
      return this._json(res, 400, {});
    }

    const mode = this.getReceiveMode();
    if (mode === 'off') return this._json(res, 403, {});

    const info = obj.info || {};
    if (info && info.fingerprint) {
      this.peerStore.upsert(normalizePeer(info, this._remoteIp(req)));
    }

    if (mode === 'contacts') {
      if (!info.fingerprint || !this.isTrusted(info.fingerprint)) {
        return this._json(res, 403, {});
      }
    }

    const fileIds = Object.keys(obj.files);
    if (fileIds.length === 0) {
      res.writeHead(204);
      return res.end();
    }

    const sessionId = uuid();
    const files = {};
    for (const fid of fileIds) {
      const f = obj.files[fid] || {};
      files[fid] = {
        id: fid,
        fileName: sanitizeFileName(f.fileName || fid),
        size: typeof f.size === 'number' ? f.size : 0,
        fileType: f.fileType || 'application/octet-stream',
        sha256: f.sha256,
        preview: f.preview,
        token: uuid(),
      };
    }
    this.sessions.set(sessionId, { sessionId, files, from: info, createdAt: Date.now() });

    const respFiles = {};
    for (const fid in files) respFiles[fid] = files[fid].token;
    return this._json(res, 200, { sessionId, files: respFiles });
  }

  _upload(req, res, url) {
    const sessionId = url.searchParams.get('sessionId');
    const fileId = url.searchParams.get('fileId');
    const token = url.searchParams.get('token');
    if (!sessionId || !fileId || !token) return this._json(res, 400, {});

    const session = this.sessions.get(sessionId);
    if (!session) return this._json(res, 403, {});
    const f = session.files[fileId];
    if (!f || f.token !== token) return this._json(res, 403, {});

    const dest = this._uniquePath(f.fileName);
    const ws = fs.createWriteStream(dest);
    let finished = false;

    ws.on('error', () => {
      if (finished) return;
      finished = true;
      this.reservedPaths.delete(dest);
      this._json(res, 500, {});
    });
    ws.on('finish', () => {
      if (finished) return;
      finished = true;
      this.reservedPaths.delete(dest);
      f.done = true;
      const item = {
        id: f.id,
        fileName: f.fileName,
        filePath: dest,
        size: f.size,
        mime: f.fileType,
        sha256: f.sha256,
        fromAlias: session.from && session.from.alias,
        fromFingerprint: session.from && session.from.fingerprint,
      };
      this.onReceived(item);
      res.writeHead(200);
      res.end();
    });

    req.on('error', () => {
      if (finished) return;
      finished = true;
      this.reservedPaths.delete(dest);
      ws.destroy();
    });

    req.pipe(ws);
  }

  _uniquePath(fileName) {
    const base = sanitizeFileName(fileName);
    const ext = path.extname(base);
    const stem = base.slice(0, base.length - ext.length);
    let candidate = path.join(this.cacheDir, base);
    let n = 1;
    while (fs.existsSync(candidate) || this.reservedPaths.has(candidate)) {
      candidate = path.join(this.cacheDir, `${stem} (${n})${ext}`);
      n += 1;
    }
    this.reservedPaths.add(candidate);
    return candidate;
  }

  _sweepSessions() {
    const now = Date.now();
    for (const [sid, s] of this.sessions) {
      if (now - s.createdAt > 10 * 60 * 1000) this.sessions.delete(sid);
    }
  }

  _readBody(req) {
    return new Promise((resolve, reject) => {
      const chunks = [];
      let size = 0;
      req.on('data', (c) => {
        size += c.length;
        if (size > 50 * 1024 * 1024) {
          reject(new Error('body too large'));
          req.destroy();
          return;
        }
        chunks.push(c);
      });
      req.on('end', () => resolve(Buffer.concat(chunks)));
      req.on('error', reject);
    });
  }

  _json(res, status, obj) {
    const body = Buffer.from(JSON.stringify(obj));
    res.writeHead(status, {
      'content-type': 'application/json',
      'content-length': body.length,
    });
    res.end(body);
  }
}

module.exports = { ReceiveServer };
