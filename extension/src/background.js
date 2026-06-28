// Service worker：
// 1) 把快捷键命令与扩展图标点击转发给当前标签页的 UI 脚本。
// 2) 根据内容脚本上报的开关状态，动态切换工具栏图标颜色（橙=开启，黑=关闭）。

const ICON_ACTIVE = "#ff8c00"; // 橙色：已开启
const ICON_INACTIVE = "#202124"; // 黑色：已关闭

// 圆角矩形工具（绘制字幕条）。
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
  ctx.fill();
}

// 用 OffscreenCanvas 动态绘制图标，免去额外图片资源。
function buildIcon(size, active) {
  const canvas = new OffscreenCanvas(size, size);
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, size, size);

  // 圆形底色：开启橙、关闭黑。
  ctx.fillStyle = active ? ICON_ACTIVE : ICON_INACTIVE;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
  ctx.fill();

  // 两条白色「字幕条」（下条更短），表意字幕。
  ctx.fillStyle = "#ffffff";
  const r = Math.max(1, size * 0.06);
  const h = Math.max(2, size * 0.13);
  roundRect(ctx, size * 0.22, size * 0.4, size * 0.56, h, r);
  roundRect(ctx, size * 0.22, size * 0.62, size * 0.4, h, r);

  return ctx.getImageData(0, 0, size, size);
}

function iconImageData(active) {
  return {
    16: buildIcon(16, active),
    32: buildIcon(32, active),
    48: buildIcon(48, active),
  };
}

// 设置图标与标题。tabId 省略时设为全局默认。
function setIcon(active, tabId) {
  const iconDetails = { imageData: iconImageData(active) };
  const titleDetails = {
    title: active
      ? "YoutubeSubSync：已开启（点击或按 Alt+Shift+Y 关闭）"
      : "YoutubeSubSync（点击或按 Alt+Shift+Y 开关）",
  };
  if (tabId != null) {
    iconDetails.tabId = tabId;
    titleDetails.tabId = tabId;
  }
  chrome.action.setIcon(iconDetails).catch(() => {});
  chrome.action.setTitle(titleDetails).catch(() => {});
}

// 安装/启动时设默认（黑色）图标。
chrome.runtime.onInstalled.addListener(() => setIcon(false));
chrome.runtime.onStartup.addListener(() => setIcon(false));
setIcon(false);

async function toggleActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) return;
  if (!/^https:\/\/www\.youtube\.com\//.test(tab.url || "")) return;
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "YTT_TOGGLE" });
  } catch (e) {
    // content script 尚未就绪时忽略。
  }
}

chrome.commands.onCommand.addListener((command) => {
  if (command === "toggle-translate") toggleActiveTab();
});

chrome.action.onClicked.addListener(() => {
  toggleActiveTab();
});

// 内容脚本上报开关状态 → 切换该标签页的图标颜色。
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg && msg.type === "YTT_STATE" && sender.tab && sender.tab.id != null) {
    setIcon(!!msg.active, sender.tab.id);
  }
});
