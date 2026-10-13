'use strict';

// Peer registry: dedupe by fingerprint, exclude self, ~60s staleness -> onPeerLost.

const VALID_DEVICE_TYPES = new Set(['mobile', 'desktop', 'web', 'headless', 'server']);

function normalizePeer(obj, ip) {
  const peer = {
    alias: obj.alias || 'Unknown',
    version: obj.version || '2.0',
    deviceType: VALID_DEVICE_TYPES.has(obj.deviceType) ? obj.deviceType : 'desktop',
    fingerprint: obj.fingerprint,
    port: typeof obj.port === 'number' ? obj.port : 53317,
    protocol: obj.protocol === 'http' ? 'http' : 'https',
    download: obj.download === true,
    ip,
  };
  if (obj.deviceModel !== undefined && obj.deviceModel !== null) {
    peer.deviceModel = obj.deviceModel;
  }
  return peer;
}

class PeerStore {
  constructor({ selfFingerprint, onPeer, onPeerLost, staleMs = 60000 }) {
    this.selfFingerprint = selfFingerprint;
    this.onPeer = typeof onPeer === 'function' ? onPeer : () => {};
    this.onPeerLost = typeof onPeerLost === 'function' ? onPeerLost : () => {};
    this.staleMs = staleMs;
    this.map = new Map();
    this.timer = null;
  }

  _toPublic(p) {
    const out = {
      alias: p.alias,
      version: p.version,
      deviceType: p.deviceType,
      fingerprint: p.fingerprint,
      port: p.port,
      protocol: p.protocol,
      download: p.download,
      ip: p.ip,
    };
    if (p.deviceModel !== undefined) out.deviceModel = p.deviceModel;
    return out;
  }

  upsert(peer) {
    if (!peer || !peer.fingerprint) return;
    if (peer.fingerprint === this.selfFingerprint) return;

    const now = Date.now();
    const existing = this.map.get(peer.fingerprint);
    if (existing) {
      let changed = false;
      for (const k of ['alias', 'version', 'deviceType', 'deviceModel', 'port', 'protocol', 'download', 'ip']) {
        if (peer[k] !== undefined && peer[k] !== existing[k]) {
          existing[k] = peer[k];
          changed = true;
        }
      }
      existing.lastSeen = now;
      if (changed) this.onPeer(this._toPublic(existing));
    } else {
      const p = Object.assign({}, peer, { lastSeen: now });
      this.map.set(p.fingerprint, p);
      this.onPeer(this._toPublic(p));
    }
  }

  getPeers() {
    return Array.from(this.map.values()).map((p) => this._toPublic(p));
  }

  get(fingerprint) {
    const p = this.map.get(fingerprint);
    return p ? this._toPublic(p) : undefined;
  }

  startTimer() {
    if (this.timer) return;
    this.timer = setInterval(() => this._sweep(), 5000);
  }

  stopTimer() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  _sweep() {
    const now = Date.now();
    for (const [fp, p] of this.map) {
      if (now - p.lastSeen > this.staleMs) {
        this.map.delete(fp);
        this.onPeerLost(fp);
      }
    }
  }
}

module.exports = { PeerStore, normalizePeer };
