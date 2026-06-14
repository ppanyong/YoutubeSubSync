// Service worker：把快捷键命令与扩展图标点击，转发给当前标签页的 UI 脚本。

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
