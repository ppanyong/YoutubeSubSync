# YoutubeSubSync · YouTube 实时中文字幕

抓取 YouTube 视频的英文字幕轨，实时翻译成中文并叠加显示。按快捷键一键开关。

这是 **MVP（第一阶段）**：走「字幕轨 → 翻译 → 叠加」路径，无需语音识别，
速度快、质量高、成本低。
覆盖没有字幕的视频与直播。
请注意，务必输入你自己的LLM配置，可以参考使用硅基流动的 tencent/Hunyuan-MT-7B 目前限免中，不会产生成本。


## 架构

```
浏览器扩展 (MV3)                         自建后端 (FastAPI)
┌──────────────────────────┐            ┌──────────────────────┐
│ background.js  快捷键开关  │            │ GET  /captions        │
│ content-main  浏览器内抓字幕│──失败回退──►│  youtube-transcript-api│
│ content-ui    翻译+叠加   │──HTTP──►   │ POST /translate       │
└──────────────────────────┘            │  └─ LLM (OpenAI兼容)   │
                                        └──────────────────────┘
```

- **content-main.js**（MAIN world）：主用「拦截播放器自身的 timedtext 请求」方式
  —— 播放器开启字幕时带着有效 POT 令牌请求，我们捕获该已鉴权 URL 再用 `fmt=json3`
  自行重拉，绕过 BotGuard，且用本机 IP+会话，最稳。失败时再退到 Innertube 等方式。
- **content-ui.js**（ISOLATED world）：浏览器全失败时才调用后端 `/captions`，
  再翻译并叠加显示。

> 关于「IP 被封 / RequestBlocked」：后端 `/captions` 发的是匿名请求，频繁调用易被
> YouTube 临时限流。**正常情况下浏览器拦截方案就能成功，不会走到后端。**
- **后端**：基于 LLM（OpenAI 兼容接口）的批量翻译。

## 快速开始（一键安装）

在项目根目录执行：

```bash
./install.sh
```

脚本会自动：检测 Python（优先 3.12）→ 创建虚拟环境 → 安装依赖 → 生成 `.env` → 启动后端（默认 `http://127.0.0.1:8000`）。

- 只想安装、暂不启动：`./install.sh --no-start`
- 装好后到 **设置页 `http://127.0.0.1:8000/`** 填入 LLM 配置，点「测试连接」确认再保存
- 再[加载扩展](#加载扩展)即可使用

> 推荐用硅基流动的 `tencent/Hunyuan-MT-7B`（目前限免，不产生成本）。
> Base URL 示例：OpenAI `https://api.openai.com/v1`、智谱 GLM `https://open.bigmodel.cn/api/paas/v4`。

## 一、启动后端

一键脚本已包含安装与启动。若需手动操作：

```bash
cd backend
# macOS 默认 python3 可能是 3.14，部分依赖尚无预编译包，建议用 3.12：
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # 然后填入你的 API Key
python main.py             # 默认监听 http://127.0.0.1:8000
```

在 `.env` 中配置 LLM（也可启动后在网页设置）：

- **推荐**：浏览器打开 `http://127.0.0.1:8000/` 在设置页填写 LLM 配置，点「测试连接」确认后再保存
- **或手动编辑 `.env`**：填 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`
  - OpenAI：`https://api.openai.com/v1`
  - 智谱 GLM：`https://open.bigmodel.cn/api/paas/v4`

验证：浏览器打开 `http://127.0.0.1:8000/health`，`translate_ready` 应为 `true`。

## 二、加载扩展
<a id="加载扩展"></a>

1. Chrome/Edge 打开 `chrome://extensions`
2. 右上角打开「开发者模式」
3. 「加载已解压的扩展程序」→ 选择本仓库的 `extension/` 目录

## 三、使用

1. 打开任意带英文字幕的 YouTube 视频
2. 按 **Alt+Shift+Y**（或点击扩展图标）开启
3. 右上角会提示「抓取字幕 → 翻译 → 已开启」，随后视频底部出现中文字幕
4. 再按一次快捷键关闭

> 快捷键可在 `chrome://extensions/shortcuts` 修改。

## 常见问题

- **提示「没有可用字幕轨」**：该视频确实无字幕，需等第二阶段的语音识别功能。
- **提示「翻译失败」**：后端未启动或 `.env` 未配置 API Key。
- **字幕不显示**：确认视频在 `www.youtube.com` 域名下播放（非嵌入页）。

