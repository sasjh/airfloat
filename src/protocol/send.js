'use strict';

// Client side of the LocalSend v2 protocol: prepare-upload then concurrent uploads.

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const MIME_BY_EXT = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.bmp': 'image/bmp',
  '.heic': 'image/heic',
  '.heif': 'image/heif',
  '.svg': 'image/svg+xml',
};

function uuid() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const b = crypto.randomBytes(16);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = b.toString('hex');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function guessMime(fileName) {
  const ext = path.extname(String(fileName)).toLowerCase();
  return MIME_BY_EXT[ext] || 'application/octet-stream';
}

function request(peer, method, reqPath, opts = {}) {
  return new Promise((resolve, reject) => {
    const mod = peer.protocol === 'http' ? http : https;
    const options = {
      host: peer.ip,
      port: peer.port,
      method,
      path: reqPath,
      headers: opts.headers || {},
    };
    if (peer.protocol !== 'http') options.rejectUnauthorized = false;

    const r = mod.request(options, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks) }));
    });
    r.on('error', reject);

    if (opts.body !== undefined) {
      const buf = Buffer.isBuffer(opts.body) ? opts.body : Buffer.from(opts.body);
      r.setHeader('content-length', buf.length);
      r.end(buf);
    } else {
      r.end();
    }
  });
}

function sha256File(filePath) {
  return new Promise((resolve, reject) => {
    const h = crypto.createHash('sha256');
    const s = fs.createReadStream(filePath);
    s.on('data', (c) => h.update(c));
    s.on('end', () => resolve(h.digest('hex')));
    s.on('error', reject);
  });
}

function uploadFile(peer, reqPath, filePath, size, fileName, onProgress) {
  return new Promise((resolve, reject) => {
    const mod = peer.protocol === 'http' ? http : https;
    const options = {
      host: peer.ip,
      port: peer.port,
      method: 'POST',
      path: reqPath,
      headers: { 'content-length': size },
    };
    if (peer.protocol !== 'http') options.rejectUnauthorized = false;

    let settled = false;
    const fail = (e) => {
      if (settled) return;
      settled = true;
      reject(e);
    };
    const ok = () => {
      if (settled) return;
      settled = true;
      resolve();
    };

    const r = mod.request(options, (res) => {
      res.resume();
      res.on('end', () => {
        if (res.statusCode === 200 || res.statusCode === 204) ok();
        else fail(new Error(`upload status ${res.statusCode}`));
      });
    });
    r.on('error', fail);

    const stream = fs.createReadStream(filePath);
    let sent = 0;
    stream.on('data', (c) => {
      sent += c.length;
      if (onProgress) onProgress({ fileName, sentBytes: sent, totalBytes: size });
      if (!r.write(c)) stream.pause();
    });
    r.on('drain', () => stream.resume());
    stream.on('end', () => r.end());
    stream.on('error', (e) => {
      r.destroy(e);
      fail(e);
    });
  });
}

async function sendFiles(peer, files, { selfInfo, onProgress }) {
  const entries = [];
  for (const f of files) {
    const stat = await fs.promises.stat(f.path);
    const fileName = f.fileName || path.basename(f.path);
    const mime = f.mime || guessMime(fileName);
    const id = uuid();
    const sha256 = await sha256File(f.path);
    entries.push({ id, fileName, size: stat.size, fileType: mime, sha256, path: f.path });
  }

  const filesObj = {};
  for (const e of entries) {
    filesObj[e.id] = {
      id: e.id,
      fileName: e.fileName,
      size: e.size,
      fileType: e.fileType,
      sha256: e.sha256,
    };
  }

  const body = Buffer.from(JSON.stringify({ info: selfInfo(), files: filesObj }));
  const resp = await request(peer, 'POST', '/api/localsend/v2/prepare-upload', {
    body,
    headers: { 'content-type': 'application/json' },
  });

  if (resp.status === 204) return; // 完成（无需传文件）
  if (resp.status !== 200) throw new Error(`prepare-upload status ${resp.status}`);

  let data;
  try {
    data = JSON.parse(resp.body.toString('utf8'));
  } catch {
    throw new Error('invalid prepare-upload response');
  }
  const sessionId = data.sessionId;
  const tokens = data.files || {};

  await Promise.all(
    entries.map(async (e) => {
      const token = tokens[e.id];
      if (!token) throw new Error(`missing token for file ${e.id}`);
      const q =
        `/api/localsend/v2/upload?sessionId=${encodeURIComponent(sessionId)}` +
        `&fileId=${encodeURIComponent(e.id)}&token=${encodeURIComponent(token)}`;
      await uploadFile(peer, q, e.path, e.size, e.fileName, onProgress);
    })
  );
}

module.exports = { request, sendFiles, guessMime, uuid };
