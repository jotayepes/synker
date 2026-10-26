import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  ModalRoot,
  PanelSection,
  PanelSectionRow,
  SliderField,
  Spinner,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import * as api from "./backend";
import { t } from "./i18n";

const humanSize = (n: number): string => {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
};

const errorText = (e: unknown): string => (e instanceof Error ? e.message : String(e));

export const toastError = (e: unknown) => toaster.toast({ title: "Synker", body: `${t("Error")}: ${errorText(e)}` });

// -- Storage ---------------------------------------------------------------

export function StorageSection({ config }: { config: api.SynkerConfig | null }) {
  const [busy, setBusy] = useState(false);
  const location = !config
    ? "…"
    : config.storage.type === "smb"
      ? config.storage.smb.host
        ? `smb://${config.storage.smb.host}/${config.storage.smb.share}/${config.storage.smb.path}`
        : t("Not configured")
      : config.storage.path || t("Not configured");

  const test = async () => {
    setBusy(true);
    try {
      const r = await api.testStorage();
      toaster.toast({ title: "Synker", body: r.ok ? `${t("Connection OK")}: ${r.location}` : `${t("Error")}: ${r.error}` });
    } finally {
      setBusy(false);
    }
  };

  const backupAll = async () => {
    setBusy(true);
    try {
      const results = await api.backupAll();
      const created = results.filter((r) => r.action === "created").length;
      const queued = results.filter((r) => r.action === "queued").length;
      toaster.toast({ title: "Synker", body: `${t("Saves backed up")}: ${created}${queued ? ` (+${queued} queued)` : ""}` });
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title={t("Storage")}>
      <PanelSectionRow>
        <div style={{ fontSize: "12px", wordBreak: "break-all" }}>{location}</div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={test}>
          {t("Test connection")}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={backupAll}>
          {busy ? <Spinner style={{ height: "16px" }} /> : t("Back up all now")}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

// -- Games -----------------------------------------------------------------

function GameModal({ status, closeModal }: { status: api.GameStatus; closeModal?: () => void }) {
  const [backups, setBackups] = useState<api.BackupEntry[] | null>(null);
  const [busy, setBusy] = useState(false);
  const gid = status.game.id;

  const reload = () =>
    api.listBackups(gid).then(setBackups).catch((e) => {
      toastError(e);
      setBackups([]);
    });
  useEffect(() => {
    reload();
  }, []);

  const run = async (fn: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await fn();
      toaster.toast({ title: status.game.title, body: message });
      await reload();
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
  };

  const confirmRestore = (b: api.BackupEntry) =>
    showModal(
      <ConfirmModal
        strTitle={t("Restore this backup?")}
        strDescription={`${b.created_iso} · ${b.device}. ${t("Current saves are kept in a local snapshot so you can undo.")}`}
        onOK={() => run(() => api.restoreGame(gid, b.id), t("Saves restored from the NAS"))}
      />,
    );

  return (
    <ModalRoot closeModal={closeModal}>
      <h2 style={{ marginTop: 0 }}>{status.game.title}</h2>
      <div style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
        <ButtonItem disabled={busy} onClick={() => run(() => api.backupGame(gid), t("Saves backed up"))}>
          {t("Back up now")}
        </ButtonItem>
        <ButtonItem disabled={busy} onClick={() => run(() => api.undoRestore(gid), t("Undo last restore"))}>
          {t("Undo last restore")}
        </ButtonItem>
      </div>
      {status.game.appid ? (
        <div style={{ fontSize: "11px", opacity: 0.7, marginBottom: "8px" }}>
          {t("Strict mode launch option")}: ~/homebrew/plugins/Synker/bin/synker run --appid {status.game.appid} -- %command%
        </div>
      ) : null}
      <h3>{t("Backups")}</h3>
      {backups === null ? (
        <Spinner style={{ height: "24px" }} />
      ) : (
        backups.map((b) => (
          <ButtonItem key={b.id} layout="inline" disabled={busy} label={b.created_iso.slice(0, 19).replace("T", " ")}
            description={`${b.device} · ${t(b.reason)} · ${b.files} ${t("files")} · ${humanSize(b.size)}${b.locked ? " · 🔒" : ""}`}
            onClick={() => confirmRestore(b)}>
            {t("Restore")}
          </ButtonItem>
        ))
      )}
    </ModalRoot>
  );
}

export function GamesSection() {
  const [statuses, setStatuses] = useState<api.GameStatus[] | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setStatuses(await api.getStatus());
    } catch (e) {
      toastError(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <PanelSection title={t("Games")}>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={loading} onClick={load}>
          {loading ? <Spinner style={{ height: "16px" }} /> : statuses ? t("Refresh") : t("Load status")}
        </ButtonItem>
      </PanelSectionRow>
      {statuses && statuses.length === 0 && (
        <PanelSectionRow>
          <div>{t("No games with saves detected")}</div>
        </PanelSectionRow>
      )}
      {statuses?.map((s) => (
        <PanelSectionRow key={s.game.id}>
          <ButtonItem layout="below" description={`${t(s.state)}${s.latest ? ` · ${s.latest.created_iso.slice(0, 16).replace("T", " ")}` : ""}`}
            onClick={() => showModal(<GameModal status={s} />)}>
            {s.game.title}
          </ButtonItem>
        </PanelSectionRow>
      ))}
    </PanelSection>
  );
}

// -- Conflict prompt -------------------------------------------------------

export function showConflictModal(gameId: string, title: string) {
  showModal(
    <ConfirmModal
      strTitle={`${t("Save conflict")}: ${title}`}
      strDescription={t("This device and the NAS both have changes. Which version do you want to keep?")}
      strOKButtonText={t("Use NAS version")}
      strCancelButtonText={t("Keep this device's version")}
      onOK={() =>
        api.resolveConflict(gameId, "keep-both").then(
          () => toaster.toast({ title, body: t("Saves restored from the NAS") }),
          toastError,
        )
      }
    />,
  );
}

// -- Settings --------------------------------------------------------------

export function SettingsSection({ config, onSaved }: { config: api.SynkerConfig | null; onSaved: (c: api.SynkerConfig) => void }) {
  const [draft, setDraft] = useState<api.SynkerConfig | null>(config);
  const [password, setPasswordValue] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setDraft(config), [config]);

  if (!draft) return null;
  const smb = draft.storage.smb;
  const update = (fn: (d: api.SynkerConfig) => void) => {
    const copy: api.SynkerConfig = JSON.parse(JSON.stringify(draft));
    fn(copy);
    setDraft(copy);
  };

  const save = async () => {
    setBusy(true);
    try {
      const saved = await api.setConfig({
        device_name: draft.device_name,
        "storage.type": draft.storage.type,
        "storage.path": draft.storage.path,
        "storage.smb.host": smb.host.trim(),
        "storage.smb.share": smb.share.trim(),
        "storage.smb.path": smb.path.trim(),
        "storage.smb.username": smb.username.trim(),
        "storage.smb.domain": smb.domain.trim(),
        "backup.auto_restore": draft.backup.auto_restore,
        "backup.backup_on_exit": draft.backup.backup_on_exit,
        "backup.periodic_minutes": draft.backup.periodic_minutes,
        "backup.include_cloud_games": draft.backup.include_cloud_games,
        "backup.conflict_policy": draft.backup.conflict_policy,
      });
      if (password) {
        await api.setPassword(password);
        setPasswordValue("");
      }
      onSaved(saved);
      const test = await api.testStorage();
      toaster.toast({ title: "Synker", body: test.ok ? `${t("Settings saved")} · ${t("Connection OK")}` : `${t("Settings saved")} · ${t("Error")}: ${test.error}` });
    } catch (e) {
      toastError(e);
    } finally {
      setBusy(false);
    }
  };

  const policies = [
    { data: "ask", label: t("Ask") },
    { data: "prefer-remote", label: t("Use NAS version") },
    { data: "prefer-local", label: t("Keep this device's version") },
    { data: "keep-both", label: t("Keep both (NAS wins, local kept as copy)") },
  ];

  return (
    <PanelSection title={t("Settings")}>
      <PanelSectionRow>
        <DropdownItem label={t("Storage type")} selectedOption={draft.storage.type}
          rgOptions={[{ data: "smb", label: t("NAS (SMB)") }, { data: "local", label: t("Local / mounted folder") }]}
          onChange={(o) => update((d) => (d.storage.type = o.data))} />
      </PanelSectionRow>
      {draft.storage.type === "smb" ? (
        <>
          <PanelSectionRow>
            <TextField label={t("Host or IP")} value={smb.host} onChange={(e) => update((d) => (d.storage.smb.host = e.target.value))} />
          </PanelSectionRow>
          <PanelSectionRow>
            <TextField label={t("Share")} value={smb.share} onChange={(e) => update((d) => (d.storage.smb.share = e.target.value))} />
          </PanelSectionRow>
          <PanelSectionRow>
            <TextField label={t("Folder in share")} value={smb.path} onChange={(e) => update((d) => (d.storage.smb.path = e.target.value))} />
          </PanelSectionRow>
          <PanelSectionRow>
            <TextField label={t("User")} value={smb.username} onChange={(e) => update((d) => (d.storage.smb.username = e.target.value))} />
          </PanelSectionRow>
          <PanelSectionRow>
            <TextField label={t("Password")} bIsPassword value={password} onChange={(e) => setPasswordValue(e.target.value)} />
          </PanelSectionRow>
          <PanelSectionRow>
            <TextField label={t("Domain (optional)")} value={smb.domain} onChange={(e) => update((d) => (d.storage.smb.domain = e.target.value))} />
          </PanelSectionRow>
        </>
      ) : (
        <PanelSectionRow>
          <TextField label={t("Folder path")} value={draft.storage.path} onChange={(e) => update((d) => (d.storage.path = e.target.value))} />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <TextField label={t("Device name")} value={draft.device_name} onChange={(e) => update((d) => (d.device_name = e.target.value))} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label={t("Restore newer saves on launch")} checked={draft.backup.auto_restore}
          onChange={(v) => update((d) => (d.backup.auto_restore = v))} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label={t("Back up when the game closes")} checked={draft.backup.backup_on_exit}
          onChange={(v) => update((d) => (d.backup.backup_on_exit = v))} />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField label={t("Periodic backup while playing (min, 0 = off)")} value={draft.backup.periodic_minutes}
          min={0} max={60} step={5} showValue onChange={(v) => update((d) => (d.backup.periodic_minutes = v))} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label={t("Include games with store cloud saves")} checked={draft.backup.include_cloud_games}
          onChange={(v) => update((d) => (d.backup.include_cloud_games = v))} />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem label={t("On conflict")} selectedOption={draft.backup.conflict_policy} rgOptions={policies}
          onChange={(o) => update((d) => (d.backup.conflict_policy = o.data))} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={save}>
          {busy ? <Spinner style={{ height: "16px" }} /> : t("Save settings")}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy}
          onClick={() => api.updateManifest().then((r) => toaster.toast({ title: "Synker", body: r.error ? r.error : `${r.games > 0 ? r.games : ""} ${t("Games")}` }), toastError)}>
          {t("Update game database")}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
