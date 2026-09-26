"use strict";
const coverState = {data: null, busy: false, dirty: false, polling: false, resultId: null, config: null};
function coverError(error = null) {
  $("cover-error").hidden = !error;
  $("cover-error").textContent = error ? error.message || String(error) : "";
}
function coverFields() {
  return {title: $("cover-title").value, style: $("cover-style").value, lyrics: $("cover-lyrics").value,
    abc: $("cover-abc").value, seed: $("cover-seed").value, cot: $("cover-mode").value,
    cfg_scale: $("cover-cfg").value === "" ? null : Number($("cover-cfg").value), revision: coverState.data?.revision ?? 0};
}
function coverControls() {
  const data = coverState.data;
  const transcribing = data && !data.original_abc && ["queued", "transcribing"].includes(data.status);
  $("cover-transcribe").disabled = coverState.busy || !data?.files.source || data.original_abc !== null || transcribing || !coverState.config?.transcription_configured;
  $("cover-transcribe").textContent = data?.original_abc != null ? "保存済みABCを再利用（採譜不要）" : "音源から採譜する";
  $("cover-generate").disabled = coverState.busy || !data?.original_abc || !$("cover-reviewed").checked;
  for (const id of ["cover-save", "cover-prepare", "cover-edited-download"]) $(id).disabled = coverState.busy || !data || transcribing;
  $("cover-upload").disabled = coverState.busy;
  $("cover-history").disabled = coverState.busy;
  $("cover-style-count").textContent = `${$("cover-style").value.length.toLocaleString()} 文字`;
  $("cover-lyrics-count").textContent = `${$("cover-lyrics").value.length.toLocaleString()} 文字`;
  for (const field of document.querySelectorAll("#cover-form input, #cover-form textarea, #cover-form select, #cover-abc")) field.disabled = coverState.busy || !!transcribing || !data;
}
async function coverAction(fn) {
  if (coverState.busy) return;
  coverState.busy = true; coverError(); coverControls();
  try { await fn(); } catch (error) { coverError(error); }
  finally { coverState.busy = false; coverControls(); }
}
function coverAudio(id, url) {
  const audio = $(id);
  audio.hidden = !url;
  if (audio.getAttribute("src") !== (url || null)) {
    audio.pause();
    if (url) audio.src = url;
    else { audio.removeAttribute("src"); audio.load(); }
  }
}
function showCover(data, fill = true) {
  coverState.data = data;
  $("cover-history").value = data.id;
  $("cover-source-name").textContent = `素材: ${data.filename || data.source_conditions?.title || data.title || "無題"}${data.source_id ? " · ライブラリの元曲は変更しません" : ""}`;
  $("cover-status").textContent = `${labels[data.status] || data.status}${data.error ? ` · ${data.error}` : ""}`;
  $("cover-warnings").hidden = !data.warnings?.length;
  const warnings = window.I18n?.localizeTree(data.warnings || []) ?? data.warnings;
  $("cover-warnings").textContent = data.warnings?.length ? `採譜警告: ${JSON.stringify(warnings)}。ABCを確認・修正してください。` : "";
  coverAudio("cover-source-audio", data.files.preview || data.files.source);
  $("cover-original-download").hidden = !data.files.original;
  if (data.files.original) $("cover-original-download").href = `${data.files.original}?download=true`;
  if (fill) {
    for (const name of ["title", "style", "lyrics", "abc", "seed"]) $(`cover-${name}`).value = data[name] ?? "";
    $("cover-mode").value = data.cot || "melody";
    $("cover-cfg").value = data.cfg_scale ?? "";
    $("cover-reviewed").checked = false;
    $("cover-used-abc").textContent = ""; $("cover-validation").textContent = "";
    coverState.dirty = false;
    $("cover-save-state").textContent = "サーバーに保存済みです。編集後は保存してください。";
  }
  coverControls();
}
async function loadCoverList() {
  const result = await api("/api/covers");
  const options = [new Option("素材を選択…", ""), ...result.covers.map(d => new Option(`${d.title || "無題"} · ${date(d.created_at)}`, d.id))];
  $("cover-history").replaceChildren(...options);
  if (coverState.data) $("cover-history").value = coverState.data.id;
}
async function openCover(id = null) {
  if (!$("cover-dialog").open) $("cover-dialog").showModal();
  await coverAction(async () => {
    coverState.config = await api("/api/covers/config");
    $("cover-config-note").textContent = coverState.config.note;
    await loadCoverList();
    if (id) {
      showCover(await api(`/api/covers/${id}`));
      coverState.resultId = null; coverAudio("cover-result-audio", null); $("cover-result-open").hidden = true;
    }
  });
  await pollCover();
}
function mayLeaveCover() { return !coverState.dirty || confirm("保存していないカバー編集があります。編集を破棄して移動しますか？"); }
function closeCover() {
  if (coverState.busy || !mayLeaveCover()) return;
  coverState.dirty = false;
  $("cover-dialog").close();
  $("cover-source-audio").pause(); $("cover-result-audio").pause();
}
$("cover-open").addEventListener("click", () => openCover(coverState.data?.id));
$("cover-close").addEventListener("click", closeCover);
$("cover-dialog").addEventListener("cancel", event => { event.preventDefault(); closeCover(); });
$("cover-from-song").addEventListener("click", async () => {
  if (!state.detail) return;
  await openCover();
  await coverAction(async () => {
    const data = await api("/api/covers/from-song", {method: "POST", body: JSON.stringify({source_id: state.detail.id})});
    await loadCoverList(); showCover(data);
    coverState.resultId = null; coverAudio("cover-result-audio", null); $("cover-result-open").hidden = true;
  });
});
$("cover-reopen").addEventListener("click", () => { if (state.detail?.cover_id) openCover(state.detail.cover_id); });
$("cover-history").addEventListener("change", async () => {
  const id = $("cover-history").value;
  if (!id || !mayLeaveCover()) { $("cover-history").value = coverState.data?.id || ""; return; }
  await openCover(id);
});
$("cover-upload").addEventListener("change", async () => {
  const file = $("cover-upload").files[0];
  if (!file || !mayLeaveCover()) return;
  await coverAction(async () => {
    const limit = file.name.toLowerCase().endsWith(".abc") ? 262144 : 104857600;
    if (!file.size || file.size > limit) throw new Error("ファイルは空にできません。音源100 MiB / ABC256 KiB以内にしてください。");
    $("cover-status").textContent = "アップロード・音声の読み取り確認中…";
    // A LAN upload/full decode can take longer than ordinary lightweight JSON APIs.
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 180000);
    let response;
    try {
      response = await fetch(`/api/covers/upload?filename=${encodeURIComponent(file.name)}`, {
        method: "POST", body: file, headers: {"Content-Type": "application/octet-stream"}, signal: controller.signal});
    } finally { clearTimeout(timeout); }
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "アップロードに失敗しました");
    await loadCoverList(); showCover(data);
    coverState.resultId = null; coverAudio("cover-result-audio", null); $("cover-result-open").hidden = true;
  });
  $("cover-upload").value = "";
});
function markCoverDirty(event) {
  if (event.target.id === "cover-reviewed") { coverControls(); return; }
  coverState.dirty = true; $("cover-reviewed").checked = false;
  $("cover-used-abc").textContent = "";
  $("cover-save-state").textContent = "未保存の編集があります。";
  coverControls();
}
$("cover-form").addEventListener("input", markCoverDirty);
$("cover-form").addEventListener("change", markCoverDirty);
$("cover-abc").addEventListener("input", markCoverDirty);
async function saveCover() {
  if (!coverState.data) throw new Error("素材を選択してください");
  if (!coverState.dirty) return;
  const data = await api(`/api/covers/${coverState.data.id}`, {method: "PUT", body: JSON.stringify(coverFields())});
  showCover(data, false); coverState.dirty = false;
  $("cover-save-state").textContent = "サーバーに保存しました。別PCでも編集を再開できます。";
}
$("cover-save").addEventListener("click", () => coverAction(saveCover));
$("cover-edited-download").addEventListener("click", () => {
  // Download the current editor contents, including edits not yet saved.
  const url = URL.createObjectURL(new Blob([$("cover-abc").value], {type: "text/plain;charset=utf-8"}));
  const a = document.createElement("a"); a.href = url; a.download = "edited.abc"; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$("cover-prepare").addEventListener("click", () => coverAction(async () => {
  const result = await api(`/api/covers/${coverState.data.id}/prepare`, {method: "POST", body: JSON.stringify({abc: $("cover-abc").value, cot: $("cover-mode").value})});
  $("cover-used-abc").textContent = result.abc;
  $("cover-validation").textContent = `コード記号: ${result.validation.original_chords} → ${result.validation.used_chords}。両声部の音符・拍子・テンポの不変性: ${result.validation.match ? "確認済み" : "不一致"}（生成音声の一致を保証するものではありません）。`;
  $("cover-used-details").open = true;
}));
function coverPending(kind, payload) {
  const name = `yue2-cover-${kind}-${coverState.data.id}`, signature = JSON.stringify(payload);
  let pending = coverState[name];
  try { pending = JSON.parse(localStorage.getItem(name)) || pending; } catch { /* memory fallback */ }
  if (!pending || pending.signature !== signature) pending = {signature, key: submissionKey()};
  coverState[name] = pending;
  try { localStorage.setItem(name, JSON.stringify(pending)); } catch { /* memory fallback */ }
  return {key: pending.key, clear: () => { delete coverState[name]; try { localStorage.removeItem(name); } catch { /* optional */ } }};
}
$("cover-transcribe").addEventListener("click", () => coverAction(async () => {
  await saveCover();
  const pending = coverPending("transcribe", {id: coverState.data.id});
  await api(`/api/covers/${coverState.data.id}/transcribe`, {method: "POST", body: JSON.stringify({submission_key: pending.key})});
  pending.clear(); showCover(await api(`/api/covers/${coverState.data.id}`), false); await refresh();
}));
$("cover-form").addEventListener("submit", event => {
  event.preventDefault();
  if (!$("cover-reviewed").checked) { coverError(new Error("ABC・警告・歌詞の確認済みにチェックしてください")); return; }
  coverAction(async () => {
    await saveCover();
    const fields = coverFields();
    const payload = {...fields, seed_mode: fields.seed === "" ? "random" : "fixed", seed: fields.seed || null,
      candidate_count: 1, reviewed: true};
    const pending = coverPending("generate", payload);
    const result = await api(`/api/covers/${coverState.data.id}/generate`, {method: "POST", body: JSON.stringify({...payload, submission_key: pending.key})});
    pending.clear(); coverState.resultId = result.jobs[0].id;
    coverAudio("cover-result-audio", null); $("cover-result-open").hidden = true;
    showCover(await api(`/api/covers/${coverState.data.id}`), false);
    $("cover-save-state").textContent = "カバーをキューに登録しました。元曲は変更されません。";
    await refresh();
  });
});
async function pollCover() {
  if (!$("cover-dialog").open || !coverState.data || coverState.busy || coverState.polling) return;
  coverState.polling = true;
  const id = coverState.data.id;
  try {
    const data = await api(`/api/covers/${id}`);
    if (coverState.data?.id !== id || coverState.busy) return;
    const changed = data.revision !== coverState.data.revision;
    if (changed && coverState.dirty) {
      coverError(new Error("別画面または採譜処理でABCが更新されました。編集内容をダウンロードしてから素材を開き直してください。"));
    } else showCover(data, changed);
    if (data.job_id) {
      const job = await api(`/api/jobs/${data.job_id}`);
      if (coverState.data?.id !== id) return;
      const url = job.files.flac || job.files.wav;
      if (url) { coverState.resultId = job.id; coverAudio("cover-result-audio", url); $("cover-result-open").hidden = false; }
    }
  } catch (error) { coverError(error); }
  finally { coverState.polling = false; }
}
setInterval(pollCover, 1800);
$("cover-result-open").addEventListener("click", async () => {
  if (!coverState.resultId || !mayLeaveCover()) return;
  const id = coverState.resultId; coverState.dirty = false; closeCover(); await selectSong(id);
  $("song-detail").scrollIntoView({block: "start"});
});
for (const [id, source] of [["compare-source", true], ["compare-output", false]]) $(id).addEventListener("click", async () => {
  const job = state.detail; if (!job) return;
  const url = source ? `/api/covers/${job.cover_id}/files/source` : job.files.flac || job.files.wav;
  if (!url) return;
  $("player-bar").hidden = false;
  $("audio").pause(); $("audio").src = url; $("audio").dataset.jobId = job.id;
  $("audio").dataset.variant = source ? "source" : "output";
  $("player-title").textContent = `${source ? "元曲" : "生成曲"}: ${source ? job.cover.source_conditions?.title || job.cover.filename || "元音源" : title(job)}`;
  $("player-meta").textContent = source ? "カバーの元音源" : `Seed ${job.seed}`;
  $("audio-error").hidden = true;
  try { await $("audio").play(); } catch (error) { toast(error.message, true); }
});
// Preserve polling playback; only a user starting another player pauses the first.
document.addEventListener("play", event => {
  if (event.target.tagName === "AUDIO") for (const audio of document.querySelectorAll("audio")) if (audio !== event.target) audio.pause();
}, true);
coverControls();

window.restoreCoverJob = async (job) => {
  await openCover(job.cover_id);
  if (!coverState.data || coverState.data.id !== job.cover_id) return;
  for (const key of ["title", "style", "lyrics", "seed"]) $(`cover-${key}`).value = job[key] ?? "";
  $("cover-mode").value = job.cot;
  $("cover-cfg").value = job.cfg_scale ?? "";
  $("cover-abc").value = job.cover.edited_abc;
  markCoverDirty({target: $("cover-abc")});
  $("cover-save-state").textContent = "選択曲の条件と編集ABCを戻しました。確認・保存してから生成できます。";
};
