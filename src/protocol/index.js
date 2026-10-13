'use strict';

// LocalSend v2 protocol module (pure Node.js, no Electron).

const os = require('os');
const path = require('path');
const cert = require('./cert');
const { PeerStore } = require('./peer-store');
const { ReceiveServer } = require('./server');
const { Discovery } = require('./discovery');
const { sendFiles } = require('./send');

/**
 * createProtocol(config) -> Promise<Api>
 * see CONTRACT.md §3 for the full config/Api contract.
 */
async function createProtocol(config) {
  config = config || {};

  const alias = config.alias || 'AirFloat';
  const version = config.version || '2.0';
  const deviceType = config.deviceType || 'desktop';
  const port = typeof config.port === 'number' ? config.port : 53317;
  const protocol = config.protocol === 'http' ? 'http' : 'https';
  const download = config.download !== undefined ? !!config.download : true;
  const deviceModel = config.deviceModel;
  const cacheDir = config.cacheDir || path.join(os.tmpdir(), 'airfloat-cache');
  const getReceiveMode =
    typeof config.getReceiveMode === 'function' ? config.getReceiveMode : () => 'everyone';
  const isTrusted = typeof config.isTrusted === 'function' ? config.isTrusted : () => false;
  const onPeer = typeof config.onPeer === 'function' ? config.onPeer : () => {};
  const onPeerLost = typeof config.onPeerLost === 'function' ? config.onPeerLost : () => {};
  const onReceived = typeof config.onReceived === 'function' ? config.onReceived : () => {};
  const onProgress = typeof config.onProgress === 'function' ? config.onProgress : () => {};

  let fingerprint;
  let tlsOptions = null;
  if (protocol === 'https') {
    const c = cert.createSelfSigned();
    fingerprint = cert.fingerprintFromCert(c.certDer);
    tlsOptions = { key: c.key, cert: c.pem };
  } else {
    fingerprint = cert.randomFingerprint();
  }

  const self = { alias, version, deviceType, fingerprint, port, protocol, download };
  if (deviceModel !== undefined && deviceModel !== null) self.deviceModel = deviceModel;

  const selfInfo = () => Object.assign({}, self);
  const getSelf = () => ({
    alias: self.alias,
    version: self.version,
    deviceType: self.deviceType,
    fingerprint: self.fingerprint,
    port: self.port,
    protocol: self.protocol,
    download: self.download,
  });

  const peerStore = new PeerStore({ selfFingerprint: fingerprint, onPeer, onPeerLost });
  const server = new ReceiveServer({
    self,
    selfInfo,
    tlsOptions,
    cacheDir,
    getReceiveMode,
    isTrusted,
    onReceived,
    peerStore,
  });
  const discovery = new Discovery({ selfInfo, fingerprint, peerStore });

  let started = false;

  async function start() {
    if (started) return;
    started = true;
    try {
      await server.start();
    } catch (e) {
      started = false;
      throw e;
    }
    discovery.start();
    peerStore.startTimer();
  }

  async function stop() {
    if (!started) return;
    started = false;
    discovery.stop();
    peerStore.stopTimer();
    await server.stop();
  }

  async function send(peer, files) {
    return sendFiles(peer, files, { selfInfo, onProgress });
  }

  return {
    start,
    stop,
    getSelf,
    getPeers: () => peerStore.getPeers(),
    send,
  };
}

module.exports = { createProtocol };
