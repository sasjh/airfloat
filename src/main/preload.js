const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('airfloat', {
  getState: () => ipcRenderer.invoke('get-state'),
  setEnabled: (v) => ipcRenderer.invoke('set-enabled', v),
  setReceiveMode: (m) => ipcRenderer.invoke('set-receive-mode', m),
  getDevices: () => ipcRenderer.invoke('get-devices'),
  sendFiles: (fingerprint, paths) => ipcRenderer.invoke('send-files', fingerprint, paths),
  dragOut: (filePath) => ipcRenderer.send('drag-out', filePath),
  getPathForFile: (file) => webUtils.getPathForFile(file),
  revealCache: () => ipcRenderer.invoke('reveal-cache'),
  onEvent: (cb) => {
    const listener = (_e, ev) => cb(ev);
    ipcRenderer.on('airfloat:event', listener);
    return () => ipcRenderer.removeListener('airfloat:event', listener);
  },
});
