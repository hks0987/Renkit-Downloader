// Service workers cannot touch the clipboard, so this hidden page does it.
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "offscreen" || msg.type !== "copy") return;
  const box = document.createElement("textarea");
  box.value = msg.text;
  document.body.appendChild(box);
  box.select();
  document.execCommand("copy");
  box.remove();
});
