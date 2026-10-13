const fs = require('fs');
const e = require('electron');
fs.writeFileSync('E:/jason de app/diag.txt', [
  'run_as_node=' + process.env.ELECTRON_RUN_AS_NODE,
  'electron=' + (process.versions.electron || 'N/A'),
  'typeof=' + typeof e,
  (typeof e === 'object' ? ('ipcMain=' + ('ipcMain' in e) + ' app=' + ('app' in e)) : ('value=' + JSON.stringify(e)))
].join('\n'));
