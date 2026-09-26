"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  let current = null, targetDetail = null, importId = null, uploadAnalysis = null, preview = null, sidecarValidated = false, newSongConditions = null;
  const voices = ["Vocal", "Ins"];
  function showError(error) { const node = $("midi-error"); node.textContent = error.message || String(error); node.hidden = false; }
  function clearError() { $("midi-error").hidden = true; }
  async function versionsFor(songId) { const data = await api(`/api/jobs/${songId}/score-versions`); if (!data.versions?.length && data.guide) throw new Error(`${data.guide.message} Cover採譜またはMIDI新規曲を選択してください`); return data.versions || []; }
  function renderVersions(rows, id) { $(id).replaceChildren(...rows.map((v) => new Option(`${v.id.slice(0, 8)} · ${v.created_at}`, v.id))); }
  async function loadSections(versionId) { const data = await api(`/api/score-versions/${versionId}/sections`); const select = $("midi-section"); select.replaceChildren(new Option("手動小節範囲", ""), ...(data.sections || []).map((s) => new Option(`${s.id} · ${s.start_bar}-${s.end_bar}小節`, s.id))); }
  async function loadTargetVersions() { try { renderVersions(await versionsFor($("midi-target-song").value), "midi-version"); } catch (error) { showError(error); } }
  function ensureConditions() {
    if ($("midi-target-style")) return;
    const box = document.createElement("div"); box.id = "midi-target-conditions";
    box.innerHTML = '<label>Style（対象曲の初期値・編集可）<textarea id="midi-target-style" rows="3"></textarea></label><label>Lyrics（対象曲の初期値・編集可）<textarea id="midi-target-lyrics" rows="5"></textarea></label><label>Seed<input id="midi-target-seed"></label>';
    $("midi-assignments").parentNode.insertBefore(box, $("midi-assignments"));
    const transpose = document.createElement("label"); transpose.innerHTML = '移調（半音、既定0）<input id="midi-transpose" type="number" min="-48" max="48" step="1" value="0">'; $("midi-assignments").parentNode.insertBefore(transpose, $("midi-assignments"));
    const link = document.createElement("div"); link.id = "midi-server-export-row"; link.innerHTML = '<label>サーバー保持export_id<input id="midi-export-id" placeholder="export_id（任意）"></label><button id="midi-export-sidecar" class="quiet" type="button">exportからsidecarを照合</button>';
    $("midi-assignments").parentNode.insertBefore(link, $("midi-assignments"));
    $("midi-export-sidecar").addEventListener("click", async () => { try { if (!importId) throw new Error("先にMIDIをアップロードしてください"); const id = $("midi-export-id").value.trim(); if (!id) throw new Error("export_idを入力してください"); const response = await fetch(`/api/midi/exports/${id}`); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "exportが見つかりません"); const result = await api(`/api/midi/imports/${importId}/sidecar`, {method: "POST", body: JSON.stringify(data)}); sidecarValidated = true; $("midi-sidecar-state").textContent = `server export照合済み · ${result.warnings?.join(" / ") || "版・範囲・ハッシュを確認しました"}`; } catch (error) { showError(error); } });
    if (!$('midi-new-seed')) { const seed = document.createElement('label'); seed.innerHTML = 'Seed<input id="midi-new-seed" inputmode="numeric" value="0">'; $('midi-new-song-panel').insertBefore(seed, $('midi-new-save')); }
  }
  async function fillConditions() {
    ensureConditions(); const target = await api(`/api/jobs/${$("midi-target-song").value}`).catch(() => current); targetDetail = target;
    $("midi-target-style").value = target?.style || ""; $("midi-target-lyrics").value = target?.lyrics || ""; $("midi-target-seed").value = target?.seed || "";
  }
  function resetImportUI() {
    $("midi-candidates").replaceChildren(); $("midi-assignments").replaceChildren(); $("midi-preview").hidden = true; $("midi-abc-diff").hidden = true;
    $("midi-analyze").disabled = true; $("midi-save").disabled = true; $("midi-regenerate").disabled = true; $("midi-new-save").disabled = true; $("midi-sidecar-attach").disabled = true;
    $("midi-sidecar-state").textContent = "sidecarなしの場合は対象版・範囲・原点を手動確定します。"; importId = null; uploadAnalysis = null; preview = null; sidecarValidated = false;
  }
  async function open(mode) {
    if (mode !== "new" && (typeof state === "undefined" || !state.detail)) { alert("曲を選択してください"); return; }
    current = mode === "new" ? null : ((typeof state !== "undefined" && state.detail) ? state.detail : null); clearError(); preview = null; newSongConditions = null; targetDetail = null; $("midi-dialog").showModal(); $("midi-export-panel").hidden = mode !== "export"; $("midi-import-panel").hidden = mode === "export"; $("midi-new-song-panel").hidden = mode === "export";
    if (mode === "export") { try { renderVersions(await versionsFor(current.id), "midi-export-version"); await loadSections($("midi-export-version").value); } catch (error) { showError(error); } }
    else { const jobs = typeof state !== "undefined" ? state.jobs : []; $("midi-target-song").replaceChildren(...jobs.map((job) => new Option(job.title || "無題の曲", job.id))); $("midi-target-song").value = current?.id || ""; ensureConditions(); resetImportUI(); const hasTarget = Boolean(current); $("midi-target-song").disabled = !hasTarget; $("midi-version").disabled = !hasTarget; $("midi-import-start").disabled = !hasTarget; $("midi-import-end").disabled = !hasTarget; $("midi-quantization").disabled = !hasTarget; if (hasTarget) { await fillConditions(); await loadTargetVersions(); } }
  }
  function renderCandidates() {
    const candidates = uploadAnalysis?.candidates || [], box = $("midi-candidates"), assignmentBox = $("midi-assignments"); box.replaceChildren(); assignmentBox.replaceChildren();
    if (!candidates.length) { box.textContent = "音符を含むtrack×channel候補がありません。"; return; }
    box.textContent = "候補を明示的にVocal / Ins / 無視へ割り当ててください。";
    for (const candidate of candidates) {
      const row = document.createElement("label"); row.className = "midi-candidate"; const select = document.createElement("select"); select.dataset.track = candidate.track; select.dataset.channel = candidate.channel; select.append(new Option("無視", "ignore"), new Option("Vocal", "Vocal"), new Option("Ins", "Ins"));
      row.append(document.createTextNode(`track ${candidate.track} / ch ${candidate.channel} · ${candidate.name || "名称なし"} · ${candidate.notes}音 · 音域 ${candidate.range[0] ?? "—"}-${candidate.range[1] ?? "—"} · 重なり ${candidate.overlaps}`), select); assignmentBox.append(row);
    }
    const confirm = document.createElement("label"); confirm.className = "cover-check"; confirm.innerHTML = '<input id="midi-assignment-confirm" type="checkbox"> 候補の割当と損失を確認しました'; assignmentBox.append(confirm);
  }
  function selectedMap() {
    const result = {};
    for (const select of $("midi-assignments").querySelectorAll("select")) { if (select.value !== "ignore") { if (result[select.value]) throw new Error(`${select.value}が複数候補に割り当てられています`); result[select.value] = {track: Number(select.dataset.track), channel: Number(select.dataset.channel)}; } }
    if (!$("midi-assignment-confirm")?.checked) throw new Error("track×channel割当を確認してください");
    if (!Object.keys(result).length) throw new Error("VocalまたはInsへ候補を割り当ててください"); return result;
  }
  async function uploadMidi() {
    const file = $("midi-file").files[0]; if (!file) throw new Error("MIDIファイルを選択してください");
    const uploadKey = crypto.randomUUID ? crypto.randomUUID().replaceAll("-", "") : `${Date.now()}midi`; const response = await fetch(`/api/midi/imports?filename=${encodeURIComponent(file.name)}&submission_key=${uploadKey}`, {method: "POST", headers: {"Content-Type": "application/octet-stream"}, body: await file.arrayBuffer()}); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "MIDI解析に失敗しました");
    importId = data.import_id; uploadAnalysis = data.analysis; if (["failed", "interrupted"].includes(data.status)) throw new Error(`MIDI解析状態: ${data.status}`); renderCandidates(); $("midi-analyze").disabled = !current; $("midi-new-save").disabled = false; $("midi-sidecar-attach").disabled = !$("midi-sidecar").files.length;
  }
  async function attachSidecar() {
    if (!importId) throw new Error("先にMIDIをアップロードしてください"); const file = $("midi-sidecar").files[0]; if (!file) throw new Error("sidecar.jsonを選択してください");
    const result = await api(`/api/midi/imports/${importId}/sidecar`, {method: "POST", body: await file.text()}); sidecarValidated = true; const scope = result.analysis?.sidecar?.scope; $("midi-sidecar-state").textContent = `sidecar照合済み · 範囲 ${scope?.start_bar ?? "—"}-${scope?.end_bar ?? "—"}小節 / 原点 ${scope?.origin_beat ?? "—"} · ${result.warnings?.join(" / ") || "ハッシュ・版を確認しました"}`;
  }
  async function analyze() {
    const body = {target_song_id: $("midi-target-song").value, target_version_id: $("midi-version").value, voice_map: selectedMap(), start_bar: Number($("midi-import-start").value), end_bar: Number($("midi-import-end").value), quantization: $("midi-quantization").value, transpose: Number($("midi-transpose").value || 0)};
    preview = {importId, ...(await api(`/api/midi/imports/${importId}/preview`, {method: "POST", body: JSON.stringify(body)}))}; $("midi-preview").textContent = JSON.stringify(window.I18n?.localizeTree({analysis: preview.analysis, warnings: preview.warnings, changed_bars: preview.changed_bars}) ?? {analysis: preview.analysis, warnings: preview.warnings, changed_bars: preview.changed_bars}, null, 2); $("midi-preview").hidden = false; const diff = preview.analysis?.note_diff || []; $("midi-note-diff").replaceChildren(...diff.map((row) => { const line = document.createElement("div"); line.textContent = `${row.voice} · ${row.bar}小節 · 拍${row.beat}: ${JSON.stringify(row.original)} → ${JSON.stringify(row.edited)}`; return line; })); $("midi-note-diff").hidden = !diff.length; $("midi-abc-diff").value = preview.edited_abc || ""; $("midi-abc-diff").hidden = false; $("midi-save").disabled = false;
  }
  async function saveVersion() { if (!preview) return; const result = await api(`/api/midi/imports/${importId}/save`, {method: "POST", body: JSON.stringify({preview_token: preview.preview_token, expected_version_id: $("midi-version").value, confirmed: true})}); preview.savedVersionId = result.version_id; $("midi-regenerate").disabled = false; alert(`新しいABC版を保存しました: ${result.version_id}`); }
  async function regenerate() {
    if (!preview?.savedVersionId || (!current && !newSongConditions)) return; const key = crypto.randomUUID ? crypto.randomUUID().replaceAll("-", "") : `${Date.now()}midi`;
    const target = newSongConditions || targetDetail || current;
    const result = await api(`/api/score-versions/${preview.savedVersionId}/generate`, {method: "POST", body: JSON.stringify({submission_key: key, title: target.title, style: newSongConditions ? target.style : $("midi-target-style").value, lyrics: newSongConditions ? target.lyrics : $("midi-target-lyrics").value, seed_mode: "fixed", seed: newSongConditions ? target.seed : ($("midi-target-seed").value || target.seed), cot: null, candidate_count: 1, cfg_scale: target.cfg_scale})}); $("midi-dialog").close(); toast("保存したABC版を生成キューへ登録しました。"); await refresh(); if (result.jobs?.[0]) await selectSong(result.jobs[0].id);
  }
  async function newSong() {
    if (!importId) throw new Error("先にMIDIをアップロードしてください"); const title = $("midi-new-title").value, style = $("midi-new-style").value, lyrics = $("midi-new-lyrics").value, seed = $("midi-new-seed").value; if (!style.trim() || !lyrics.trim() || !/^[0-9]{1,19}$/.test(seed) || BigInt(seed) >= 2n ** 63n) throw new Error("新規曲のStyle、Lyrics、Seedを正しく入力してください"); const meter = $("midi-new-meter").value.split("/").map(Number); const result = await api(`/api/midi/imports/${importId}/new-song`, {method: "POST", body: JSON.stringify({voice_map: selectedMap(), title, style, lyrics, seed, bpm: Number($("midi-new-bpm").value), meter_n: meter[0], meter_d: meter[1], key: $("midi-new-key").value})}); newSongConditions = {title, style, lyrics, seed, cfg_scale: null}; preview = {savedVersionId: result.version_id}; $("midi-regenerate").disabled = false; alert(`新規ABCを保存しました。譜面版: ${result.version_id} / cot=${result.cot}`);
  }
  $("midi-export-open").addEventListener("click", () => open("export")); $("midi-import-open").addEventListener("click", () => open("import")); $("midi-new-open").addEventListener("click", () => open("new")); $("midi-new-open-composer").addEventListener("click", () => open("new")); $("midi-close").addEventListener("click", () => $("midi-dialog").close());
  $("midi-export-version").addEventListener("change", async () => { try { await loadSections($("midi-export-version").value); } catch (error) { showError(error); } }); $("midi-section").addEventListener("change", () => { const selected = Boolean($("midi-section").value); $("midi-start").disabled = selected; $("midi-end").disabled = selected; if (selected) { $("midi-start").value = "1"; $("midi-end").value = ""; } });
  async function exportMidi(kind) { try { const choice = $("midi-voices").value; const section = $("midi-section").value || null; const key = crypto.randomUUID ? crypto.randomUUID().replaceAll("-", "") : `${Date.now()}midi`; const data = await api("/api/midi/exports", {method: "POST", body: JSON.stringify({job_id: current.id, submission_key: key, version_id: $("midi-export-version").value, voices: choice === "both" ? voices : [choice], section_id: section, start_bar: Number($("midi-start").value), end_bar: $("midi-end").value ? Number($("midi-end").value) : null})}); if (data.status !== "ready") throw new Error(`MIDI書き出し状態: ${data.status || "unknown"}`); const link = document.createElement("a"); link.href = `/api/midi/exports/${data.export_id}/files/${kind}`; link.download = kind === "bundle" ? "yue2-midi-roundtrip.zip" : "score.mid"; link.click(); } catch (error) { showError(error); } }
  $("midi-export").addEventListener("click", () => exportMidi("bundle")); $("midi-export-mid").addEventListener("click", () => exportMidi("mid")); $("midi-file").addEventListener("change", async () => { try { resetImportUI(); await uploadMidi(); } catch (error) { showError(error); } }); $("midi-sidecar").addEventListener("change", () => { $("midi-sidecar-attach").disabled = !importId || !$("midi-sidecar").files.length; }); $("midi-sidecar-attach").addEventListener("click", async () => { try { await attachSidecar(); } catch (error) { showError(error); } }); $("midi-target-song").addEventListener("change", async () => { try { await fillConditions(); await loadTargetVersions(); } catch (error) { showError(error); } }); $("midi-analyze").addEventListener("click", async () => { try { await analyze(); } catch (error) { showError(error); } }); $("midi-save").addEventListener("click", async () => { try { await saveVersion(); } catch (error) { showError(error); } }); $("midi-regenerate").addEventListener("click", async () => { try { await regenerate(); } catch (error) { showError(error); } }); $("midi-new-save").addEventListener("click", async () => { try { await newSong(); } catch (error) { showError(error); } });
})();
