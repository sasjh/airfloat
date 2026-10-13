# CLAUDE.md — AirFloat 项目工作指引

> 本文件是 AI 协作的工作入口。**每次开始工作前，先读本文件，再读 `docs/README.md`。**

## 项目是什么

Windows 小浮窗 App「AirFloat」：基于 LocalSend v2 协议，与 iPhone 官方 LocalSend App 在同一 WiFi 下**互传图片**。淡蓝主题、iOS 设置页风格、Win+V 剪贴板那种小浮窗尺寸。

## 标准文件路径（先读这些）

| 内容 | 路径 |
|---|---|
| 文档索引 | `docs/README.md` |
| 需求规格 | `docs/01-需求规格说明书.md` |
| 技术方案 | `docs/02-技术方案.md` |
| UI 设计规范 | `docs/03-UI设计规范.md` |
| 开发计划与执行步骤 | `docs/04-开发计划与执行步骤.md` |
| 测试与验收标准 | `docs/05-测试与验收标准.md` |
| LocalSend v2 协议参考 | `docs/06-协议参考-LocalSend-v2.md` |
| 团队接口契约 | `CONTRACT.md` |
| 开发日志（每日） | `devlog/`（约定见 `devlog/README.md`） |

## 工作说明

1. **小步推进**：一次只做一个里程碑，完成并**验证通过**后再进入下一个，不一口气堆代码。
2. **每次开工**：读本文件 → 运行 `node scripts/devlog.js` 生成当日日志 → 按 `docs/04` 推进当前里程碑。
3. **每次收工**：把「完成事项 / 待办 / 风险」写入当日 `devlog/YYYY-MM-DD.md`。
4. **改接口前**：先改对应 docs 与 `CONTRACT.md`，保持文档与代码一致。
5. **新增依赖/工具前**：先记录到当日 devlog，说明用途与来源（国内镜像优先）。
6. **环境约束**：本机 GitHub 直连被墙，npm 走 npmmirror、Electron 走 `ELECTRON_MIRROR`；沙箱内用 Node 自带 TLS（勿用 git/curl 的 schannel）。
