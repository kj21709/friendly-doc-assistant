const api = (window.APP_CONFIG.API_URL || "").replace(/\/$/, "");
let userId = "", documentId = "", pollTimer;
const $ = (id) => document.getElementById(id);

function message(text, kind = "system") {
  const el = document.createElement("div");
  el.className = `message ${kind}`;
  el.textContent = text;
  $("messages").append(el);
  el.scrollIntoView({behavior:"smooth"});
  return el;
}

function resetMessages(text = "Upload a document and I’ll answer questions using only that document.") {
  $("messages").replaceChildren();
  message(text, "assistant");
}

async function jsonFetch(path, options = {}) {
  const result = await fetch(api + path, {...options, headers:{"content-type":"application/json", ...(options.headers || {})}});
  const data = await result.json().catch(() => ({}));
  if (!result.ok) throw new Error(data.message || `Request failed (${result.status})`);
  return data;
}

async function loadDocuments() {
  try {
    const data = await jsonFetch(`/documents?userId=${encodeURIComponent(userId)}`);
    const select = $("documents");
    select.replaceChildren(new Option("Select a ready document", ""));
    data.documents.filter((doc) => doc.status === "READY").forEach((doc) => select.add(new Option(doc.filename, doc.documentId)));
  } catch (error) {
    message(error.message, "system error");
  }
}

function renderHistory(items, emptyText = "No saved chat history was found for this user.") {
  $("messages").replaceChildren();
  if (!items.length) {
    message(emptyText, "system");
    return;
  }
  items.forEach((turn) => {
    message(turn.question, "user");
    message(turn.response, "assistant");
  });
}

async function loadHistory(automatic = false) {
  try {
    const data = await jsonFetch(`/history?userId=${encodeURIComponent(userId)}`);
    if (data.history.length) {
      renderHistory(data.history);
      if (automatic) message("Previous-session history restored. Select a document to continue, or type history, clear history, or exit.", "system");
    } else if (!automatic) {
      renderHistory([]);
    }
  } catch (error) {
    message(error.message, "system error");
  }
}

function endSession() {
  clearInterval(pollTimer);
  userId = "";
  documentId = "";
  $("workspace").classList.add("hidden");
  $("welcome").classList.remove("hidden");
  $("status").textContent = "Start a session";
  $("nameForm").reset();
  $("chatForm").reset();
  $("file").value = "";
  $("fileInfo").textContent = "";
  $("documents").replaceChildren(new Option("None ready", ""));
  $("question").disabled = $("send").disabled = true;
  resetMessages();
  $("name").focus();
}

async function clearHistory() {
  const data = await jsonFetch("/history", {method:"DELETE", body:JSON.stringify({userId})});
  resetMessages(data.cleared ? `Cleared ${data.cleared} saved chat ${data.cleared === 1 ? "turn" : "turns"}.` : "There was no saved chat history to clear.");
}

$("name").addEventListener("input", (event) => {
  const start = event.target.selectionStart;
  const end = event.target.selectionEnd;
  event.target.value = event.target.value.toLocaleUpperCase();
  event.target.setSelectionRange(start, end);
});

$("nameForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  userId = $("name").value.trim().replace(/\s+/g, " ").toLocaleUpperCase();
  $("name").value = userId;
  if (userId.length < 2) return;
  $("welcome").classList.add("hidden");
  $("workspace").classList.remove("hidden");
  $("status").textContent = `Session: ${userId}`;
  $("question").disabled = $("send").disabled = false;
  await Promise.all([loadDocuments(), loadHistory(true)]);
  $("question").focus();
});

$("documents").addEventListener("change", (event) => {
  documentId = event.target.value;
  const label = event.target.options[event.target.selectedIndex]?.text || "";
  if (documentId) {
    $("fileInfo").textContent = `Ready • ${label}`;
    message(`Continuing with ${label}.`, "assistant");
    $("question").focus();
  }
});

$("file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 12 * 1024 * 1024) { message("File is larger than 5 MB.", "system error"); return; }
  clearInterval(pollTimer);
  documentId = "";
  $("fileInfo").textContent = "Preparing upload…";
  try {
    const type = file.type || "application/octet-stream";
    const init = await jsonFetch("/uploads", {method:"POST", body:JSON.stringify({userId, filename:file.name, size:file.size, contentType:type})});
    documentId = init.documentId;
    const uploaded = await fetch(init.uploadUrl, {method:"PUT", headers:{"content-type":type}, body:file});
    if (!uploaded.ok) throw new Error("S3 upload failed.");
    $("fileInfo").textContent = "Vectorizing document…";
    message(`Processing ${file.name}. This can take a few minutes.`, "system");
    pollTimer = setInterval(checkStatus, 3000);
    await checkStatus();
  } catch (error) {
    $("fileInfo").textContent = "Upload failed";
    message(error.message, "system error");
  }
});

async function checkStatus() {
  try {
    const data = await jsonFetch(`/documents/status?userId=${encodeURIComponent(userId)}&documentId=${encodeURIComponent(documentId)}`);
    const doc = data.document;
    if (doc.status === "READY") {
      clearInterval(pollTimer);
      $("fileInfo").textContent = `Ready • ${doc.chunkCount} chunks • ${doc.filename}`;
      await loadDocuments();
      $("documents").value = documentId;
      $("question").focus();
      message("Your document is ready. What would you like to know?", "assistant");
    } else if (doc.status === "FAILED") {
      clearInterval(pollTimer);
      $("fileInfo").textContent = "Processing failed";
      message(doc.errorMessage || "Document processing failed.", "system error");
    }
  } catch (error) {
    console.error(error);
  }
}

$("question").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("chatForm").requestSubmit();
  }
});

$("chatForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("question").value.trim();
  if (!question) return;
  const command = question.toLocaleLowerCase().replace(/\s+/g, " ");
  $("question").value = "";

  if (command === "exit" || command === "bye") {
    endSession();
    return;
  }

  message(question, "user");
  if (command === "history") {
    await loadHistory();
    $("question").focus();
    return;
  }
  if (command === "clear history") {
    try { await clearHistory(); } catch (error) { message(error.message, "system error"); }
    $("question").focus();
    return;
  }
  if (!documentId) {
    message("Select or upload a ready document before asking a question.", "system error");
    $("question").focus();
    return;
  }

  $("question").disabled = $("send").disabled = true;
  const waiting = message("Dave is reading…", "assistant");
  try {
    const data = await jsonFetch("/chat", {method:"POST", body:JSON.stringify({userId, documentId, question})});
    waiting.textContent = data.answer;
  } catch (error) {
    waiting.textContent = error.message;
    waiting.classList.add("error");
  } finally {
    $("question").disabled = $("send").disabled = false;
    $("question").focus();
  }
});
