'use strict';

// Self test: two createProtocol instances (protocol:'http', distinct ports, 127.0.0.1)
// exchange one temporary byte file; assert onReceived bytes match.

const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { createProtocol } = require('./index');

async function main() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'airfloat-test-'));
  const payload = crypto.randomBytes(512 * 1024 + 17); // odd size to catch truncation
  const payloadPath = path.join(tmp, 'payload.bin');
  fs.writeFileSync(payloadPath, payload);

  let resolveReceived;
  const receivedPromise = new Promise((r) => {
    resolveReceived = r;
  });

  const sender = await createProtocol({
    alias: 'Sender',
    deviceType: 'desktop',
    version: '2.0',
    port: 15331,
    protocol: 'http',
    download: true,
    cacheDir: path.join(tmp, 'sender-cache'),
    getReceiveMode: () => 'everyone',
    onReceived: () => {},
  });

  const receiver = await createProtocol({
    alias: 'Receiver',
    deviceType: 'desktop',
    version: '2.0',
    port: 15332,
    protocol: 'http',
    download: true,
    cacheDir: path.join(tmp, 'receiver-cache'),
    getReceiveMode: () => 'everyone',
    onReceived: (item) => resolveReceived(item),
  });

  await sender.start();
  await receiver.start();

  const peer = Object.assign({}, receiver.getSelf(), { ip: '127.0.0.1' });

  await sender.send(peer, [{ path: payloadPath }]);

  const item = await receivedPromise;
  const got = fs.readFileSync(item.filePath);

  assert.strictEqual(item.size, payload.length, 'metadata size mismatch');
  assert.strictEqual(Buffer.compare(got, payload), 0, 'received bytes mismatch');

  await sender.stop();
  await receiver.stop();

  console.log('PASS');
  process.exit(0);
}

const timeout = setTimeout(() => {
  console.log('FAIL: timeout');
  process.exit(1);
}, 15000);

main()
  .catch((e) => {
    console.log('FAIL: ' + (e && e.stack ? e.stack : e));
    process.exit(1);
  })
  .finally(() => clearTimeout(timeout));
