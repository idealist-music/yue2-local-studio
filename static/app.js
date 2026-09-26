"use strict";
const $ = (id) => document.getElementById(id);
const state = {jobs: [], selected: null, detail: null, source: null, favorites: false, paused: false, listKey: "", queueKey: "", pending: null, submitting: false, deletedIds: new Set()};
const deletion = {id: null, preview: null, busy: false, origin: null};
const labels = {queued: "待機中", transcribing: "採譜中", awaiting_review: "ABC確認待ち", reviewed: "ABC確認済み", needs_transcription: "採譜が必要", running: "生成中", completed: "完了", truncated: "打ち切りあり", failed: "失敗", interrupted: "中断", cancelled: "キャンセル済み"};
const draftKey = "yue2-studio-draft-v1";
const pendingKey = "yue2-studio-submission-v1";
let toastTimer;

function submissionKey() {
  // getRandomValues is also available on HTTP LAN origins, unlike randomUUID.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function toast(message, error = false) {
  $("toast").textContent = message;
  $("toast").className = error ? "error" : "";
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 10000 : 5000);
}
async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
  const response = await fetch(path, {cache: "no-store", ...options, signal: controller.signal, headers: {"Content-Type": "application/json", ...options.headers}});
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(e => `${e.loc.slice(1).join(".")}: ${e.msg}`).join(" / ") : data.detail;
    const error = new Error(detail || `エラー (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("サーバーの応答が10秒以内に届きません。接続を確認してください。同じ送信は安全に再試行できます。");
    throw error;
  } finally { clearTimeout(timeout); }
}
function duration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const n = Math.max(0, Math.floor(seconds));
  return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
}
function date(value) { return new Date(value).toLocaleString("ja-JP", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"}); }
function title(job) { return job.title || "無題の曲"; }
function fields() {
  return {title: $("title").value, style: $("style").value, lyrics: $("lyrics").value, cot: $("cot").value,
    seed_mode: $("seed-mode").value, seed: $("seed-mode").value === "fixed" ? $("seed").value : null,
    candidate_count: Number($("candidate-count").value), cfg_scale: $("cfg").value === "" ? null : Number($("cfg").value),
    source_id: state.source?.id || null};
}
function updateForm() {
  $("seed").disabled = $("seed-mode").value !== "fixed";
  $("seed").required = $("seed-mode").value === "fixed";
  $("lyrics-count").textContent = `${$("lyrics").value.length.toLocaleString()} 文字`;
  $("style-count").textContent = `${$("style").value.length.toLocaleString()} 文字`;
  $("score-source").hidden = !state.source;
  $("source-title").textContent = state.source ? `元曲: ${state.source.title || "無題の曲"}` : "";
  for (const option of $("cot").options) {
    option.disabled = !!state.source && (option.value === "off" || (state.source.has_chords && option.value !== "full"));
  }
}
function saveDraft() {
  updateForm();
  try {
    localStorage.setItem(draftKey, JSON.stringify({...fields(), seed_input: $("seed").value, source: state.source}));
    $("draft-state").textContent = "下書き保存済み · このブラウザで復元できます。";
  } catch {
    $("draft-state").textContent = "下書きを保存できません。ブラウザの保存領域を確認してください。";
  }
}
function fillForm(data, source = null) {
  $("title").value = data.title ?? "";
  $("style").value = data.style ?? "";
  $("lyrics").value = data.lyrics ?? "";
  $("cot").value = data.cot || "full";
  $("seed-mode").value = data.seed_mode || "fixed";
  $("seed").value = data.seed_input ?? data.seed ?? "";
  $("candidate-count").value = String(data.candidate_count || 1);
  $("cfg").value = data.cfg_scale ?? "";
  state.source = source;
  updateForm();
}
function restoreDraft() {
  try {
    const saved = JSON.parse(localStorage.getItem(draftKey) || "null");
    if (saved) fillForm(saved, saved.source || null);
    state.pending = JSON.parse(localStorage.getItem(pendingKey) || "null");
    if (state.pending) $("draft-state").textContent = "前回の送信結果が未確認です。同じ内容を送信すると重複せず確認できます。";
  } catch { $("draft-state").textContent = "保存済み下書きを読み込めませんでした。"; }
  updateForm();
}

$("compose-form").addEventListener("input", saveDraft);
$("compose-form").addEventListener("change", saveDraft);
for (const [field, label] of [["style", "Style"], ["lyrics", "Lyrics"]]) {
  $(`${field}-clear`).addEventListener("click", () => {
    if (!window.confirm(`${label}欄の内容をすべて消去しますか？`)) return;
    $(field).value = "";
    saveDraft();
    $(field).focus();
  });
}
$("score-clear").addEventListener("click", () => { state.source = null; saveDraft(); });
$("compose-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.submitting) return;
  const payload = fields();
  if (payload.seed_mode === "fixed") {
    try {
      if (!/^[0-9]{1,19}$/.test(payload.seed) || BigInt(payload.seed) >= 2n ** 63n) throw new Error();
    } catch { toast("Seed は 0〜9223372036854775807 の整数で入力してください。", true); return; }
  }
  if (!payload.style.trim() || !payload.lyrics.trim()) { toast("Style と Lyrics を入力してください。", true); return; }
  const signature = JSON.stringify(payload);
  if (!state.pending || state.pending.signature !== signature) {
    state.pending = {signature, key: submissionKey()};
  }
  try { localStorage.setItem(pendingKey, JSON.stringify(state.pending)); } catch { /* In-memory retry still works. */ }
  state.submitting = true;
  $("generate").disabled = true;
  $("generate").textContent = "キューに登録しています…";
  try {
    const result = await api("/api/jobs", {method: "POST", body: JSON.stringify({...payload, submission_key: state.pending.key})});
    state.pending = null;
    try { localStorage.removeItem(pendingKey); } catch { /* No persistent storage. */ }
    toast(`${result.jobs.length}曲を${result.reused ? "登録済みのキューで確認しました" : "キューに登録しました"}。`);
    await refresh();
    await selectSong(result.jobs[0].id);
  } catch (error) { toast(error.message, true); }
  finally {
    state.submitting = false;
    $("generate").disabled = false;
    $("generate").textContent = "曲を生成する ↗";
  }
});

function renderQueue(status) {
  state.paused = status.paused;
  $("queue-toggle").textContent = status.paused ? "キュー再開・ワーカー再起動" : "一時停止";
  $("queue-toggle").disabled = status.paused && !!status.active_id;
  $("queue-reason").hidden = !status.paused;
  $("queue-reason").textContent = status.reason;
  $("test-banner").hidden = status.engine !== "test";
  const jobs = state.jobs.filter(j => ["queued", "running", "transcribing", "awaiting_review"].includes(j.status)).sort((a,b) => a.created_at.localeCompare(b.created_at) || a.candidate_index - b.candidate_index);
  $("queue-count").textContent = String(jobs.length);
  const key = JSON.stringify(jobs.map(j => [j.id, j.status, j.started_at]));
  if (key !== state.queueKey) {
    state.queueKey = key;
    const nodes = jobs.map(job => {
      const row = el("div", "queue-item");
      row.append(el("span", `queue-indicator ${job.status}`));
      const info = el("div", "queue-info");
      const name = el("button", "quiet small queue-title", title(job));
      name.type = "button"; name.addEventListener("click", () => selectSong(job.id));
      const meta = el("span", "queue-sub", `${labels[job.status]} · ${job.candidate_index}/${job.candidate_count}曲目`);
      if (job.started_at) { const time = el("span"); time.dataset.started = job.started_at; meta.append(time); }
      info.append(name, meta); row.append(info);
      if (job.status === "queued") {
        const cancel = el("button", "quiet small", "キャンセル"); cancel.type = "button";
        cancel.addEventListener("click", async () => {
          cancel.disabled = true;
          try { await api(`/api/jobs/${job.id}/cancel`, {method: "POST", body: "{}"}); await refresh(); }
          catch (e) { toast(e.message, true); cancel.disabled = false; }
        }); row.append(cancel);
      }
      return row;
    });
    $("queue-items").replaceChildren(...(nodes.length ? nodes : [el("p", "empty-small", "キューは空です。新しい曲を待っています。") ]));
  }
  const log = status.logs.join("\n") || "ワーカーは初回生成時に起動します。";
  if ($("live-log").textContent !== log) { $("live-log").textContent = log; $("live-log").scrollTop = $("live-log").scrollHeight; }
  tick();
}
function tick() {
  for (const node of document.querySelectorAll("[data-started]")) node.textContent = ` · 経過 ${duration((Date.now() - Date.parse(node.dataset.started)) / 1000)}`;
}
async function toggleFavorite(job) {
  try { await api(`/api/jobs/${job.id}/favorite`, {method: "PATCH", body: JSON.stringify({favorite: !job.favorite})}); await refresh(); }
  catch (e) { toast(e.message, true); }
}
function showDeleteError(message) {
  $("delete-error").textContent = message;
  $("delete-error").hidden = false;
}
async function openDelete(job, origin) {
  if (deletion.busy || $("delete-dialog").open) return;
  deletion.id = job.id; deletion.origin = origin; deletion.preview = null;
  $("delete-title").textContent = title(job);
  $("delete-summary").textContent = "削除対象を確認しています…";
  $("delete-preserved").textContent = "";
  $("delete-error").hidden = true;
  $("delete-confirm").disabled = true;
  $("delete-dialog").showModal();
  try {
    const preview = await api(`/api/jobs/${job.id}/deletion`);
    if (deletion.id !== job.id || !$("delete-dialog").open) return;
    deletion.preview = preview;
    $("delete-title").textContent = preview.title || title(job);
    $("delete-summary").textContent = `この項目の履歴・専用ファイル、譜面版 ${preview.score_versions} 件、MIDI書き出し ${preview.midi_exports} 件、MIDI取込み ${preview.midi_imports} 件を削除します。`;
    $("delete-preserved").textContent = preview.preserved;
    $("delete-confirm").disabled = false;
  } catch (error) {
    if (deletion.id === job.id && $("delete-dialog").open) {
      $("delete-summary").textContent = "削除できません";
      showDeleteError(error.message);
    }
  }
}
$("delete-cancel").addEventListener("click", () => { if (!deletion.busy) $("delete-dialog").close(); });
$("delete-dialog").addEventListener("cancel", event => { if (deletion.busy) event.preventDefault(); });
$("delete-dialog").addEventListener("close", () => { if (!deletion.busy) { deletion.id = null; deletion.preview = null; deletion.origin = null; } });
$("delete-confirm").addEventListener("click", async () => {
  if (deletion.busy || !deletion.preview || !deletion.id) return;
  const id = deletion.id, origin = deletion.origin;
  deletion.busy = true;
  $("delete-confirm").disabled = true;
  $("delete-cancel").disabled = true;
  $("delete-confirm").textContent = "削除中…";
  $("delete-error").hidden = true;
  try {
    const result = await api(`/api/jobs/${id}`, {method: "DELETE"});
    state.deletedIds.add(id);
    state.jobs = state.jobs.filter(item => item.id !== id);
    state.listKey = ""; state.queueKey = "";
    if (state.selected === id) {
      state.selected = null; state.detail = null;
      $("song-detail").hidden = true;
      if ($("audio").dataset.jobId === id) {
        $("audio").pause(); $("audio").removeAttribute("src"); $("audio").load();
        $("audio").dataset.jobId = ""; $("player-bar").hidden = true;
      }
    }
    renderLibrary();
    deletion.busy = false;
    $("delete-dialog").close();
    await refresh();
    if (origin === "detail") $("search").focus();
    toast(result.cleanup_pending ? "削除済み。ファイル整理は次回起動時に再試行します。" : "削除が完了しました。");
  } catch (error) {
    showDeleteError(error.message);
  } finally {
    deletion.busy = false;
    $("delete-cancel").disabled = false;
    $("delete-confirm").textContent = "削除";
    $("delete-confirm").disabled = !deletion.preview;
  }
});
function renderLibrary() {
  const query = $("search").value.toLocaleLowerCase();
  const rows = state.jobs.filter(j => (!state.favorites || j.favorite) && j.title.toLocaleLowerCase().includes(query));
  $("library-count").textContent = String(rows.length);
  const key = JSON.stringify([state.selected, rows]);
  if (key === state.listKey) return;
  state.listKey = key;
  if (!rows.length) {
    const box = el("div", "empty-library");
    box.append(el("span", "empty-symbol", "♫"), el("h3", "", state.jobs.length ? "一致する曲はありません" : "最初の一曲をつくりましょう"), el("p", "", "生成した曲を聴き比べて、お気に入りを残せます。"));
    $("song-list").replaceChildren(box); return;
  }
  $("song-list").replaceChildren(...rows.map(job => {
    const row = el("article", `song-row${state.selected === job.id ? " selected" : ""}`);
    const select = el("button", "song-select"); select.type = "button";
    select.setAttribute("aria-label", `${title(job)} 候補${job.candidate_index} ${labels[job.status]}`);
    select.setAttribute("aria-pressed", String(state.selected === job.id));
    const words = el("span", "track-text");
    const trackTitle = el("span", "track-title", `${title(job)}${job.engine === "test" ? " ［テスト音声］" : ""}`);
    trackTitle.id = `library-title-${job.id}`;
    words.append(trackTitle,
      el("span", "track-meta", `${date(job.created_at)} · 候補 ${job.candidate_index}/${job.candidate_count} · ${duration(job.duration)}`),
      el("span", "track-meta", `Seed ${job.seed}`));
    select.append(el("span", "track-art", job.status === "running" ? "⋯" : "♪"), words);
    select.addEventListener("click", () => selectSong(job.id));
    const favorite = el("button", "favorite-button", job.favorite ? "★" : "☆"); favorite.type = "button";
    favorite.setAttribute("aria-label", `${title(job)}を${job.favorite ? "お気に入りから外す" : "お気に入りに追加"}`);
    favorite.setAttribute("aria-pressed", String(job.favorite)); favorite.addEventListener("click", () => toggleFavorite(job));
    const remove = el("button", "delete-song-button"); remove.type = "button";
    remove.setAttribute("aria-label", "曲を削除"); remove.title = "曲を削除";
    remove.setAttribute("aria-describedby", trackTitle.id);
    remove.append(el("span", "", "🗑")); remove.firstChild.setAttribute("aria-hidden", "true");
    remove.addEventListener("click", () => openDelete(job, "library"));
    row.append(select, el("span", `track-status status-${job.status}`, labels[job.status]), favorite, remove);
    return row;
  }));
}
function renderDetail(job) {
  state.detail = job;
  $("song-detail").hidden = false;
  $("detail-title").textContent = title(job);
  $("detail-meta").textContent = `${labels[job.status]} · 候補 ${job.candidate_index}/${job.candidate_count} · ${duration(job.duration)} · Seed ${job.seed}${job.engine === "test" ? " · テスト音声（YuE2生成ではありません）" : ""}`;
  $("detail-error").hidden = !job.error && job.status !== "truncated";
  $("detail-error").textContent = job.error ? `${job.error} (${job.error_code})` : "生成がトークン上限に達した部分があります。音声の終端を確認してください。";
  $("detail-favorite").textContent = job.favorite ? "★ お気に入り" : "☆ お気に入り";
  $("detail-favorite").setAttribute("aria-pressed", String(job.favorite));
  $("detail-style").textContent = job.style;
  $("detail-lyrics").textContent = job.lyrics;
  $("detail-settings").textContent = JSON.stringify({mode: job.cot, seed: job.seed, cfg_scale: job.cfg_scale ?? "YuE2既定値", group_id: job.group_id, source_id: job.source_id, source_title: job.source_title, uses_score: job.uses_score, truncated: job.truncated, created_at: job.created_at, started_at: job.started_at, finished_at: job.finished_at}, null, 2);
  $("reuse-score").hidden = !job.files.abc;
  $("cover-from-song").hidden = job.task === "transcribe" || !(job.files.abc || job.files.flac || job.files.wav || job.uses_score);
  $("cover-reopen").hidden = !job.cover_id;
  $("compare-source").hidden = !job.cover?.audio_name;
  $("compare-output").hidden = !job.cover || !(job.files.flac || job.files.wav);
  $("restore").hidden = job.task === "transcribe";
  $("regenerate").hidden = job.task === "transcribe";
  $("reuse-explanation").hidden = !job.files.abc;
  const names = {flac: "FLAC ↓", wav: "WAV ↓", conditions: "生成条件 JSON ↓", abc: "ABC ↓", result: "公式結果 JSON ↓", config: "公式設定 JSON ↓"};
  if (job.cover && job.task !== "transcribe") {
    for (const [kind, label] of Object.entries({cover: "カバー記録 JSON ↓", "original-abc": "元ABC ↓", "edited-abc": "編集ABC ↓", "used-abc": "使用ABC ↓"})) {
      names[kind] = label; job.files[kind] = `/api/jobs/${job.id}/files/${kind}`;
    }
  }
  $("downloads").replaceChildren(...Object.entries(names).filter(([kind]) => job.files[kind]).map(([kind, label]) => {
    const link = el("a", "", label); link.href = `${job.files[kind]}?download=true`; link.download = ""; return link;
  }));
  const playable = job.files.flac || job.files.wav;
  if (playable) {
    $("player-bar").hidden = false;
    $("player-title").textContent = title(job);
    $("player-meta").textContent = `候補 ${job.candidate_index}/${job.candidate_count} · ${duration(job.duration)}${job.engine === "test" ? " · テスト音声" : ""}`;
    if ($("audio").dataset.jobId !== job.id) {
      $("audio").pause();
      $("audio").src = playable;
      $("audio").dataset.jobId = job.id;
      $("audio").dataset.variant = "output";
      $("audio-error").hidden = true;
    }
    if ($("audio").dataset.variant === "source" && job.cover) {
      $("player-title").textContent = `元曲: ${job.cover.source_conditions?.title || job.cover.filename || "元音源"}`;
      $("player-meta").textContent = "カバーの元音源";
    }
  }
}
async function selectSong(id) {
  state.selected = id; renderLibrary();
  try {
    const job = await api(`/api/jobs/${id}`);
    if (state.selected !== id) return;
    renderDetail(job);
    if ($("track-log-details").open) await loadTrackLog();
  } catch (e) { toast(e.message, true); }
}
async function loadTrackLog() {
  const id = state.selected;
  if (!id) return;
  try { const log = await api(`/api/jobs/${id}/logs`); if (state.selected === id) $("track-log").textContent = log.text; }
  catch (e) { $("track-log").textContent = e.message; }
}
$("track-log-details").addEventListener("toggle", () => { if ($("track-log-details").open) loadTrackLog(); });
$("detail-favorite").addEventListener("click", () => { if (state.detail) toggleFavorite(state.detail); });
$("detail-delete").addEventListener("click", () => { if (state.detail) openDelete(state.detail, "detail"); });
$("restore").addEventListener("click", () => {
  const job = state.detail; if (!job) return;
  if (job.cover_id && window.restoreCoverJob) { window.restoreCoverJob(job); return; }
  fillForm({...job, candidate_count: 1}, job.uses_score ? {id: job.source_id, title: job.source_title, has_chords: job.cot === "full"} : null);
  saveDraft(); $("title").focus(); $("compose-heading").scrollIntoView({block: "start"});
  toast("フォームに条件を戻しました。内容を変更して新しい曲を生成できます。");
});
$("reuse-score").addEventListener("click", () => {
  const job = state.detail; if (!job) return;
  fillForm({...job, candidate_count: 1}, {id: job.id, title: job.title, has_chords: job.has_chords});
  saveDraft(); $("style").focus(); $("compose-heading").scrollIntoView({block: "start"});
  toast("保存済み譜面を選択しました。スタイル・歌詞を調整して生成してください。");
});
$("regenerate").addEventListener("click", async () => {
  const job = state.detail; if (!job || $("regenerate").disabled) return;
  $("regenerate").disabled = true;
  const keyName = `yue2-retry-${job.id}`;
  let key = submissionKey();
  try { key = localStorage.getItem(keyName) || key; localStorage.setItem(keyName, key); } catch { /* In-memory submission only. */ }
  try {
    const result = await api(`/api/jobs/${job.id}/regenerate`, {method: "POST", body: JSON.stringify({submission_key: key})});
    try { localStorage.removeItem(keyName); } catch { /* No persistent storage. */ }
    toast("同じ条件・Seedで、新しい曲をキューに登録しました。"); await refresh(); await selectSong(result.jobs[0].id);
  } catch (e) { toast(e.message, true); }
  finally { $("regenerate").disabled = false; }
});
$("queue-toggle").addEventListener("click", async () => {
  $("queue-toggle").disabled = true;
  try { await api(`/api/queue/${state.paused ? "resume" : "pause"}`, {method: "POST", body: "{}"}); await refresh(); }
  catch (e) { toast(e.message, true); }
  finally { $("queue-toggle").disabled = false; }
});
$("search").addEventListener("input", renderLibrary);
$("favorites-filter").addEventListener("click", () => {
  state.favorites = !state.favorites; $("favorites-filter").setAttribute("aria-pressed", String(state.favorites)); renderLibrary();
});
$("player-stop").addEventListener("click", () => { $("audio").pause(); $("audio").currentTime = 0; });
$("audio").addEventListener("error", () => { $("audio-error").hidden = false; });
$("diagnostics-open").addEventListener("click", async () => {
  $("diagnostics").showModal(); $("diagnostics-content").textContent = "確認しています…";
  try { const diagnostic = await api("/api/diagnostics"); $("diagnostics-content").textContent = JSON.stringify(window.I18n?.localizeTree(diagnostic) ?? diagnostic, null, 2); }
  catch (e) { $("diagnostics-content").textContent = e.message; }
});
$("diagnostics-close").addEventListener("click", () => $("diagnostics").close());
let refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const [result, status] = await Promise.all([api("/api/jobs"), api("/api/status")]);
    const previous = state.jobs.find(j => j.id === state.selected);
    state.jobs = result.jobs.filter(job => !state.deletedIds.has(job.id)); renderQueue(status); renderLibrary();
    const selected = state.jobs.find(j => j.id === state.selected);
    if (selected && (!previous || JSON.stringify(previous) !== JSON.stringify(selected))) await selectSong(selected.id);
    if (!selected && state.selected) {
      state.selected = null; state.detail = null; $("song-detail").hidden = true;
      if ($("audio").dataset.jobId && !state.jobs.some(job => job.id === $("audio").dataset.jobId)) {
        $("audio").pause(); $("audio").removeAttribute("src"); $("audio").load();
        $("audio").dataset.jobId = ""; $("player-bar").hidden = true;
      }
      state.listKey = ""; renderLibrary();
    }
    if ($("track-log-details").open) await loadTrackLog();
    $("connection").textContent = "ローカル接続"; $("connection").classList.remove("offline");
  } catch {
    $("connection").textContent = "再接続待ち"; $("connection").classList.add("offline");
  } finally { refreshing = false; }
}
restoreDraft(); refresh();
setInterval(refresh, 1500); setInterval(tick, 1000);
let checkingHealth = false;
async function checkHealth() {
  if (checkingHealth) return;
  checkingHealth = true;
  try {
    const health = await api("/api/health");
    const names = {not_started: "モデル未準備（初回生成時に読み込み）", loading: "モデル読み込み中", transcribing: "SheetSage2採譜中", generating: "生成中", ready: "生成準備完了", error: "ワーカー異常"};
    $("health-state").textContent = !health.ready ? (health.error || "保存データを復旧中です。画面は引き続き操作できます。") : (names[health.worker_state] || health.worker_state);
    $("health-state").title = health.error || "";
  } catch (error) { $("health-state").textContent = error.message; }
  finally { checkingHealth = false; }
}
checkHealth(); setInterval(checkHealth, 2000);
