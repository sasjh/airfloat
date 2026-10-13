'use strict';

// Self-signed X.509 v1 (RSA-SHA256) certificate generation using only Node's crypto.
// fingerprint = SHA-256(hex) of the certificate DER, matching LocalSend v2.

const crypto = require('crypto');

// --- minimal ASN.1 DER helpers ---

// tag-length-value
function tl(tag, body) {
  const len = body.length;
  let lenBuf;
  if (len < 0x80) {
    lenBuf = Buffer.from([len]);
  } else {
    const b = [];
    let l = len;
    while (l > 0) {
      b.unshift(l & 0xff);
      l = Math.floor(l / 256);
    }
    lenBuf = Buffer.from([0x80 | b.length].concat(b));
  }
  return Buffer.concat([Buffer.from([tag]), lenBuf, body]);
}

function derInteger(bytes) {
  let b = Buffer.from(bytes);
  while (b.length > 1 && b[0] === 0x00) b = b.subarray(1);
  if (b.length === 0) b = Buffer.from([0]);
  if (b[0] & 0x80) b = Buffer.concat([Buffer.from([0x00]), b]);
  return tl(0x02, b);
}

function derOid(oid) {
  const parts = oid.split('.').map(Number);
  const out = [parts[0] * 40 + parts[1]];
  for (let i = 2; i < parts.length; i++) {
    let v = parts[i];
    const stack = [v & 0x7f];
    v = Math.floor(v / 128);
    while (v > 0) {
      stack.unshift((v & 0x7f) | 0x80);
      v = Math.floor(v / 128);
    }
    out.push(...stack);
  }
  return tl(0x06, Buffer.from(out));
}

function derNull() {
  return Buffer.from([0x05, 0x00]);
}

function rsaAlgId() {
  return tl(0x30, Buffer.concat([derOid('1.2.840.113549.1.1.1'), derNull()]));
}

function sha256WithRsaAlgId() {
  return tl(0x30, Buffer.concat([derOid('1.2.840.113549.1.1.11'), derNull()]));
}

function derName(cn) {
  const rdn = tl(
    0x31,
    tl(0x30, Buffer.concat([derOid('2.5.4.3'), tl(0x0c, Buffer.from(cn, 'utf8'))]))
  );
  return tl(0x30, rdn);
}

function derUtcTime(date) {
  const s = [
    String(date.getUTCFullYear() % 100).padStart(2, '0'),
    String(date.getUTCMonth() + 1).padStart(2, '0'),
    String(date.getUTCDate()).padStart(2, '0'),
    String(date.getUTCHours()).padStart(2, '0'),
    String(date.getUTCMinutes()).padStart(2, '0'),
    String(date.getUTCSeconds()).padStart(2, '0'),
    'Z',
  ].join('');
  return tl(0x17, Buffer.from(s, 'ascii'));
}

function rsaPublicKeyInfo(modulusHex, exponentHex) {
  const mod = derInteger(Buffer.from(modulusHex, 'hex'));
  const exp = derInteger(Buffer.from(exponentHex, 'hex'));
  const rsaPub = tl(0x30, Buffer.concat([mod, exp]));
  const bitString = tl(0x03, Buffer.concat([Buffer.from([0x00]), rsaPub]));
  return tl(0x30, Buffer.concat([rsaAlgId(), bitString]));
}

function toPemCert(der) {
  const b64 = der.toString('base64');
  const lines = b64.match(/.{1,64}/g).join('\n');
  return `-----BEGIN CERTIFICATE-----\n${lines}\n-----END CERTIFICATE-----\n`;
}

function createSelfSigned() {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('rsa', {
    modulusLength: 2048,
  });
  const jwk = publicKey.export({ format: 'jwk' });
  const modulusHex = Buffer.from(jwk.n, 'base64url').toString('hex');
  const exponentHex = Buffer.from(jwk.e, 'base64url').toString('hex');

  const serial = crypto.randomBytes(16);
  serial[0] &= 0x7f; // keep positive

  const now = new Date();
  const notBefore = new Date(now.getTime() - 86400000); // 1 day grace
  const notAfter = new Date(now.getTime() + 10 * 365 * 86400000); // 10 years

  const name = derName('AirFloat');
  const tbs = tl(
    0x30,
    Buffer.concat([
      derInteger(serial),
      sha256WithRsaAlgId(),
      name,
      tl(0x30, Buffer.concat([derUtcTime(notBefore), derUtcTime(notAfter)])),
      name,
      rsaPublicKeyInfo(modulusHex, exponentHex),
    ])
  );

  const signature = crypto.sign('RSA-SHA256', tbs, privateKey);
  const certDer = tl(
    0x30,
    Buffer.concat([
      tbs,
      sha256WithRsaAlgId(),
      tl(0x03, Buffer.concat([Buffer.from([0x00]), signature])),
    ])
  );

  return {
    certDer,
    pem: toPemCert(certDer),
    key: privateKey.export({ format: 'pem', type: 'pkcs8' }),
  };
}

function fingerprintFromCert(certDer) {
  return crypto.createHash('sha256').update(certDer).digest('hex');
}

function randomFingerprint() {
  return crypto.randomBytes(32).toString('hex');
}

module.exports = { createSelfSigned, fingerprintFromCert, randomFingerprint };
