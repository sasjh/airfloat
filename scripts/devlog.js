// 开发日志助手：每次开工运行，自动创建当日日志；--add 追加记录。
// 用法：
//   node scripts/devlog.js               # 确保当日日志存在，打印路径
//   node scripts/devlog.js --add "文字"   # 在「今日完成」下追加带时间戳的一行
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const dir = path.join(root, 'devlog');
fs.mkdirSync(dir, { recursive: true });

const now = new Date();
const pad = (n) => String(n).padStart(2, '0');
const ymd = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
const hhmm = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
const file = path.join(dir, `${ymd}.md`);

const template = `# 开发日志 ${ymd}\n\n## 今日完成\n- \n\n## 今日待办\n- \n\n## 风险与阻塞\n- \n\n## 明日计划\n- \n`;

if (!fs.existsSync(file)) {
  fs.writeFileSync(file, template, 'utf8');
  console.log('已创建当日日志:', file);
} else {
  console.log('当日日志已存在:', file);
}

const args = process.argv.slice(2);
if (args[0] === '--add' && args.length > 1) {
  const line = `- [${hhmm}] ${args.slice(1).join(' ')}`;
  const content = fs.readFileSync(file, 'utf8');
  fs.writeFileSync(file, content.replace('## 今日完成\n', `## 今日完成\n${line}\n`), 'utf8');
  console.log('已追加:', line);
}
