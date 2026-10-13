// 从镜像下载 Electron 压缩包（Node 自带 TLS，绕过沙箱 schannel；自动跟随跳转）
const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const [url, out] = process.argv.slice(2);
fs.mkdirSync(path.dirname(out), { recursive: true });

function get(u, redirects = 0) {
  if (redirects > 5) { console.error('too many redirects'); process.exit(1); }
  const lib = u.startsWith('https:') ? https : http;
  lib.get(u, (r) => {
    if (r.statusCode >= 300 && r.statusCode < 400 && r.headers.location) {
      const next = new URL(r.headers.location, u).toString();
      console.error('redirect ->', next);
      r.resume();
      return get(next, redirects + 1);
    }
    if (r.statusCode !== 200) { console.error('status', r.statusCode); process.exit(1); }
    const w = fs.createWriteStream(out);
    r.pipe(w);
    w.on('finish', () => { console.log('OK bytes', fs.statSync(out).size); process.exit(0); });
  }).on('error', (e) => { console.error('ERR', e.message); process.exit(1); });
}
get(url);
