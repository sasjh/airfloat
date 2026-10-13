'use strict';

// UDP multicast discovery: group 224.0.0.167:53317, broadcast announce, reply to announce.

const dgram = require('dgram');
const { normalizePeer } = require('./peer-store');
const { request } = require('./send');

const MULTICAST_ADDR = '224.0.0.167';
const MULTICAST_PORT = 53317;

class Discovery {
  constructor({ selfInfo, fingerprint, peerStore }) {
    this.selfInfo = selfInfo;
    this.fingerprint = fingerprint;
    this.peerStore = peerStore;
    this.socket = null;
    this.timer = null;
  }

  start() {
    if (this.socket) return;
    let socket;
    try {
      socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });
    } catch {
      return; // discovery unavailable, not fatal
    }
    this.socket = socket;

    socket.on('message', (msg, rinfo) => this._onMessage(msg, rinfo));
    socket.on('error', () => {}); // swallow; discovery is best-effort
    socket.on('listening', () => {
      try { socket.setBroadcast(true); } catch {}
      try { socket.setMulticastTTL(1); } catch {}
      try { socket.setMulticastLoopback(true); } catch {}
      try { socket.addMembership(MULTICAST_ADDR); } catch {}
      this._broadcast();
      this.timer = setInterval(() => this._broadcast(), 30000);
    });

    try {
      socket.bind(MULTICAST_PORT);
    } catch {}
  }

  _broadcast() {
    if (!this.socket) return;
    const msg = Buffer.from(JSON.stringify(Object.assign({}, this.selfInfo(), { announce: true })));
    try {
      this.socket.send(msg, MULTICAST_PORT, MULTICAST_ADDR);
    } catch {}
  }

  _onMessage(msg, rinfo) {
    let obj;
    try {
      obj = JSON.parse(msg.toString('utf8'));
    } catch {
      return;
    }
    if (!obj || typeof obj !== 'object' || !obj.fingerprint) return;
    if (obj.fingerprint === this.fingerprint) return;

    const peer = normalizePeer(obj, rinfo.address);
    this.peerStore.upsert(peer);

    if (obj.announce === true) {
      this._replyRegister(peer);
    }
  }

  async _replyRegister(peer) {
    try {
      const resp = await request(peer, 'POST', '/api/localsend/v2/register', {
        body: Buffer.from(JSON.stringify(this.selfInfo())),
        headers: { 'content-type': 'application/json' },
      });
      if (resp.status === 200) {
        let obj = {};
        try {
          obj = JSON.parse(resp.body.toString('utf8'));
        } catch {}
        if (obj && obj.fingerprint) {
          this.peerStore.upsert(normalizePeer(obj, peer.ip));
        }
      }
    } catch {}
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    if (this.socket) {
      try { this.socket.close(); } catch {}
      this.socket = null;
    }
  }
}

module.exports = { Discovery, MULTICAST_ADDR, MULTICAST_PORT };
