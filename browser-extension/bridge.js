(function exposeBridge(root) {
  async function sendToPage(chromeApi, tabId, message) {
    try {
      return await chromeApi.tabs.sendMessage(tabId, message);
    } catch (error) {
      if (!/Receiving end does not exist|Could not establish connection/i.test(error?.message || "")) throw error;
      await chromeApi.scripting.executeScript({
        target: { tabId },
        files: ["ats-adapter.js", "matcher.js", "grouping.js", "content.js"]
      });
      return chromeApi.tabs.sendMessage(tabId, message);
    }
  }

  root.RecruitmentAutofillBridge = { sendToPage };
})(globalThis);
