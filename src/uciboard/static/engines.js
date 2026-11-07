// The list of engines: the two pickers (live analysis, game analysis) and the dialog that adds,
// edits and removes engines. All the logic is in Python (engines.py, api.py); this only shows it.

const $ = (id) => document.getElementById(id);
const MANAGE = "__manage__";

export function initEngines({ api, onLiveChanged }) {
  let list = null;                       // the last answer of api.engines()
  const pickers = [["live", $("pick-live")], ["evolution", $("pick-evo")]];

  function show(answer) {
    list = answer;
    for (const [role, select] of pickers) {
      select.textContent = "";
      for (const e of list.engines) {
        const o = document.createElement("option");
        o.value = e.id;
        o.textContent = e.found ? e.name : `${e.name} (not found)`;
        o.title = e.path;
        select.append(o);
      }
      const manage = document.createElement("option");
      manage.value = MANAGE;
      manage.textContent = "Add or edit engines…";
      select.append(manage);
      select.value = list[role] || (list.engines[0] && list.engines[0].id) || MANAGE;
      select.title = (role === "live"
        ? "The engine for the live analysis of the board"
        : "The engine that analyses the whole game for the graph") + (select.selectedOptions[0]
        ? `: ${select.selectedOptions[0].title}` : "");
    }
    drawDialog();
  }

  async function refresh() {
    show(await api().engines());
  }

  for (const [role, select] of pickers) {
    select.addEventListener("change", async () => {
      if (select.value === MANAGE) {
        select.value = list[role] || "";
        openDialog();
        return;
      }
      const r = await api().choose_engine(role, select.value);
      show(r);
      if (role === "live") onLiveChanged();
    });
  }

  // ---------------------------------------------------------------- the dialog
  const dialog = $("engines-dialog");
  const box = $("engines-list");
  const msg = $("engines-msg");

  function say(text, bad) {
    msg.textContent = text || "";
    msg.classList.toggle("bad", !!bad);
  }

  function openDialog() {
    say("");
    drawDialog();
    if (!dialog.open) dialog.showModal();
  }

  function row(e) {
    const el = document.createElement("div");
    el.className = "eng-row";
    el.dataset.id = e.id;
    const head = document.createElement("div");
    head.className = "eng-head";
    const name = document.createElement("input");
    name.className = "eng-name";
    name.value = e.name;
    name.disabled = e.default;
    name.setAttribute("aria-label", "Name");
    head.append(name);
    const roles = document.createElement("span");
    roles.className = "eng-roles muted";
    roles.textContent = [list.live === e.id ? "live" : "", list.evolution === e.id ? "game analysis" : ""]
      .filter(Boolean).join(" · ");
    head.append(roles);
    el.append(head);
    const path = document.createElement("div");
    path.className = "eng-path" + (e.found ? "" : " bad");
    path.textContent = e.found ? e.path : `${e.path} — no program here`;
    el.append(path);
    if (e.default) {
      const note = document.createElement("div");
      note.className = "muted eng-note";
      note.textContent = "Found by uciboard (command line, config file or PATH). Its threads and hash come from the config file.";
      el.append(note);
      return el;
    }
    const opts = document.createElement("textarea");
    opts.className = "eng-options";
    opts.rows = 3;
    opts.spellcheck = false;
    opts.value = e.options;
    opts.placeholder = "Options, one per line:\nThreads=4\nHash=1024";
    opts.setAttribute("aria-label", "Options");
    el.append(opts);
    const buttons = document.createElement("div");
    buttons.className = "eng-buttons";
    const save = document.createElement("button");
    save.textContent = "Save";
    save.className = "eng-save";
    save.addEventListener("click", async () => {
      const r = await api().update_engine(e.id, name.value, opts.value);
      show(r);
      say(r.ok ? `${name.value.trim() || e.name} saved.` : r.message, !r.ok);
      if (r.ok) onLiveChanged();
    });
    const remove = document.createElement("button");
    remove.textContent = "Remove";
    remove.className = "eng-remove quiet";
    remove.addEventListener("click", async () => {
      const r = await api().remove_engine(e.id);
      show(r);
      say(r.ok ? `${e.name} removed.` : r.message, !r.ok);
      onLiveChanged();
    });
    buttons.append(save, remove);
    el.append(buttons);
    return el;
  }

  function drawDialog() {
    box.textContent = "";
    if (!list) return;
    if (!list.engines.length) {
      const none = document.createElement("div");
      none.className = "muted";
      none.textContent = "No engine yet. Add one: any program that speaks UCI.";
      box.append(none);
    }
    for (const e of list.engines) box.append(row(e));
    if (list.error) say(list.error, true);
  }

  $("eng-add").addEventListener("click", async () => {
    let path = await api().pick_engine_file();
    if (!path) path = ($("eng-path").value || "").trim();
    if (!path) { say("Choose the engine program, or type its path in the box.", true); return; }
    say("Starting it to read its name…");
    $("eng-add").disabled = true;
    try {
      const r = await api().add_engine(path, "");
      show(r);
      if (r.ok) { $("eng-path").value = ""; say(`Added ${r.engines.find((e) => e.id === r.added).name}.`); }
      else say(r.message, true);
    } finally {
      $("eng-add").disabled = false;
    }
  });
  $("eng-close").addEventListener("click", () => dialog.close());

  return { refresh, show, setBusy(on) { $("pick-evo").disabled = on; } };
}
