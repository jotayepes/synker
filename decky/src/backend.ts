import { callable } from "@decky/api";

export interface SmbConfig {
  host: string;
  share: string;
  path: string;
  username: string;
  domain: string;
  port: number;
  encrypt: boolean;
}

export interface SynkerConfig {
  device_name: string;
  storage: { type: "local" | "smb"; path: string; smb: SmbConfig };
  backup: {
    keep_last: number;
    keep_daily_days: number;
    periodic_minutes: number;
    include_cloud_games: boolean;
    auto_restore: boolean;
    conflict_policy: string;
    backup_on_exit: boolean;
  };
}

export interface GameInfo {
  id: string;
  title: string;
  source: string;
  appid: number | null;
}

export interface BackupEntry {
  id: string;
  created_iso: string;
  device: string;
  os: string;
  reason: string;
  files: number;
  size: number;
  locked: boolean;
}

export interface GameStatus {
  game: GameInfo;
  state: string;
  local_files: number;
  local_size: number;
  latest: BackupEntry | null;
  queued: number;
}

export interface SyncResult {
  game_id?: string;
  action: string;
  state?: string;
  error?: string;
}

export const getConfig = callable<[], SynkerConfig>("get_config");
export const setConfig = callable<[values: Record<string, unknown>], SynkerConfig>("set_config");
export const setPassword = callable<[password: string], { stored_in: string }>("set_password");
export const testStorage = callable<[], { ok: boolean; location?: string; error?: string }>("test_storage");
export const updateManifest = callable<[], { updated: boolean; games: number; error: string | null }>("update_manifest");
export const getStatus = callable<[], GameStatus[]>("status");
export const backupGame = callable<[gameId: string], SyncResult[]>("backup");
export const backupAll = callable<[], SyncResult[]>("backup_all");
export const listBackups = callable<[gameId: string], BackupEntry[]>("list_backups");
export const restoreGame = callable<[gameId: string, backupId: string], SyncResult>("restore");
export const undoRestore = callable<[gameId: string], SyncResult>("undo_restore");
export const resolveConflict = callable<[gameId: string, policy: string], SyncResult>("resolve_conflict");
export const gameStarted = callable<[appid: number, name: string], SyncResult>("game_started");
export const gameStopped = callable<[appid: number], SyncResult>("game_stopped");
