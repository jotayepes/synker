import { staticClasses } from "@decky/ui";
import { addEventListener, definePlugin, removeEventListener, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaSave } from "react-icons/fa";
import * as api from "./backend";
import { GamesSection, SettingsSection, StorageSection, showConflictModal, toastError } from "./components";
import { t } from "./i18n";

function Content() {
  const [config, setConfig] = useState<api.SynkerConfig | null>(null);
  useEffect(() => {
    api.getConfig().then(setConfig, toastError);
  }, []);
  return (
    <>
      <StorageSection config={config} />
      <GamesSection />
      <SettingsSection config={config} onSaved={setConfig} />
    </>
  );
}

// appid -> display name of the games we told the backend about.
const tracked = new Map<number, string>();

function appName(appid: number): string {
  try {
    return window.appStore?.GetAppOverviewByAppID(appid)?.display_name ?? "";
  } catch {
    return "";
  }
}

function runningAppIds(): Set<number> {
  try {
    return new Set((window.SteamUIStore?.RunningApps ?? []).map((a) => Number(a.appid)));
  } catch {
    return new Set();
  }
}

function onLaunch(appid: number) {
  if (!appid || tracked.has(appid)) return;
  const name = appName(appid);
  tracked.set(appid, name);
  api.gameStarted(appid, name).catch((e) => console.error("synker: game_started failed", e));
}

function onMaybeStopped(appid: number) {
  // Non-Steam shortcuts report appid 0 here, so fall back to the running app list.
  const stillRunning = runningAppIds();
  const candidates = appid && tracked.has(appid) ? [appid] : [...tracked.keys()];
  for (const id of candidates) {
    if (id === appid || !stillRunning.has(id)) {
      tracked.delete(id);
      api.gameStopped(id).catch((e) => console.error("synker: game_stopped failed", e));
    }
  }
}

type EventPayload = { name?: string; error?: string; result?: api.SyncResult };

function onBackendEvent(kind: string, payload: EventPayload) {
  const title = payload.name || "Synker";
  const action = payload.result?.action;
  if (kind === "error") {
    toaster.toast({ title, body: `${t("Error")}: ${payload.error}` });
  } else if (kind === "started" && action === "restored") {
    toaster.toast({ title, body: t("Saves restored from the NAS") });
  } else if (kind === "started" && action === "restore-available") {
    toaster.toast({ title, body: t("A newer save is on the NAS") });
  } else if (kind === "started" && action === "ask" && payload.result?.game_id) {
    showConflictModal(payload.result.game_id, title);
  } else if (kind === "stopped" && action === "created") {
    toaster.toast({ title, body: t("Saves backed up") });
  } else if ((kind === "stopped" || kind === "periodic") && action === "queued") {
    toaster.toast({ title, body: t("NAS unreachable, backup queued") });
  }
}

export default definePlugin(() => {
  const listener = addEventListener<[kind: string, payload: EventPayload]>("synker_event", onBackendEvent);

  const actionReg = window.SteamClient.Apps.RegisterForGameActionStart((_actionId, appId, action) => {
    if (action === "LaunchApp") onLaunch(Number(appId));
  });
  const lifetimeReg = window.SteamClient.GameSessions.RegisterForAppLifetimeNotifications((n) => {
    if (n.bRunning) onLaunch(n.unAppID);
    else onMaybeStopped(n.unAppID);
  });

  return {
    name: "Synker",
    titleView: <div className={staticClasses.Title}>Synker</div>,
    content: <Content />,
    icon: <FaSave />,
    onDismount() {
      removeEventListener("synker_event", listener);
      actionReg.unregister();
      lifetimeReg.unregister();
    },
  };
});
