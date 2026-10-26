"""Tiny translation table for the desktop GUI (English source strings, Spanish translation)."""

from __future__ import annotations

import locale
import os

ES = {
    "Games": "Juegos",
    "Settings": "Ajustes",
    "Log": "Registro",
    "Game": "Juego",
    "Source": "Origen",
    "State": "Estado",
    "Files": "Archivos",
    "Latest backup": "Último backup",
    "Refresh": "Actualizar",
    "Back up selected": "Backup del seleccionado",
    "Back up all": "Backup de todo",
    "Backups / restore…": "Copias / restaurar…",
    "Ignore": "Ignorar",
    "Add custom game…": "Añadir juego personalizado…",
    "Device name": "Nombre del dispositivo",
    "Storage type": "Tipo de almacenamiento",
    "NAS (SMB)": "NAS (SMB)",
    "Local / mounted folder": "Carpeta local / montada",
    "Folder": "Carpeta",
    "Browse…": "Examinar…",
    "Host or IP": "Host o IP",
    "Port": "Puerto",
    "Share": "Recurso compartido",
    "Folder in share": "Carpeta dentro del recurso",
    "User": "Usuario",
    "Password": "Contraseña",
    "(unchanged)": "(sin cambios)",
    "Domain": "Dominio",
    "Encrypt (SMB3)": "Cifrar (SMB3)",
    "Test connection": "Probar conexión",
    "Restore newer saves when a game starts": "Restaurar partidas más nuevas al iniciar un juego",
    "Back up when a game closes": "Hacer backup al cerrar un juego",
    "Periodic backup while playing (minutes, 0 = off)": "Backup periódico jugando (minutos, 0 = no)",
    "Include games that have store cloud saves": "Incluir juegos con guardado en la nube de la tienda",
    "Backups kept": "Copias que se conservan",
    "Daily backups kept (days)": "Copias diarias conservadas (días)",
    "On conflict": "En caso de conflicto",
    "Ask": "Preguntar",
    "Use NAS version": "Usar la versión del NAS",
    "Keep this device's version": "Mantener la versión de este dispositivo",
    "Keep both": "Mantener ambas",
    "Save": "Guardar",
    "Start with the session": "Iniciar con la sesión",
    "Update game database": "Actualizar base de datos de juegos",
    "Automatic backups (daemon)": "Backups automáticos (demonio)",
    "Show": "Mostrar",
    "Quit": "Salir",
    "Saved": "Guardado",
    "Connection OK": "Conexión correcta",
    "Error": "Error",
    "Working…": "Trabajando…",
    "Restore": "Restaurar",
    "Lock / unlock": "Bloquear / desbloquear",
    "Undo last restore": "Deshacer última restauración",
    "Restore this backup? Current saves are kept in a local snapshot.":
        "¿Restaurar esta copia? Las partidas actuales se guardan en una instantánea local.",
    "Date": "Fecha",
    "Device": "Dispositivo",
    "Reason": "Motivo",
    "Size": "Tamaño",
    "Locked": "Bloqueada",
    "Configure where to store backups first.": "Primero configura dónde guardar las copias.",
    "Name": "Nombre",
    "Paths (one per line, placeholders like <home> allowed)":
        "Rutas (una por línea, se admiten marcadores como <home>)",
    "Process names (comma separated, optional)": "Nombres de proceso (separados por comas, opcional)",
    "synced": "sincronizado",
    "local-newer": "pendiente de subir",
    "remote-newer": "más nuevo en el NAS",
    "conflict": "conflicto",
    "local-only": "sin backup",
    "remote-only": "solo en el NAS",
    "empty": "vacío",
    "offline": "NAS no disponible",
    "steam": "Steam",
    "steam-shortcut": "Atajo de Steam",
    "heroic-epic": "Heroic (Epic)",
    "heroic-gog": "Heroic (GOG)",
    "lutris": "Lutris",
    "emulator": "Emulador",
    "custom": "Personalizado",
    "detected": "Detectado",
    "exit": "al cerrar",
    "periodic": "periódico",
    "manual": "manual",
    "conflict-copy": "copia de conflicto",
}


def _is_spanish() -> bool:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if os.environ.get(var):
            return os.environ[var].lower().startswith("es")
    try:
        lang = locale.getlocale()[0] or ""
    except ValueError:
        lang = ""
    return lang.lower().startswith(("es", "spanish"))


_SPANISH = _is_spanish()


def tr(text: str) -> str:
    return ES.get(text, text) if _SPANISH else text
