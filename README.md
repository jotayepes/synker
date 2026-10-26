# Synker

Respaldo automático de partidas guardadas en tu NAS (SMB) o en una carpeta, para juegos y emuladores que no tienen guardado en la nube. Funciona en **Linux**, **Windows** y **SteamOS** (como plugin de [Decky Loader](https://decky.xyz)).

*English summary at the end.*

## Qué hace

- **Detecta solo dónde guarda cada juego** usando el [manifest de ludusavi](https://github.com/mtkennerly/ludusavi-manifest), que cubre más de 23.000 juegos con datos de guardado:
  - Juegos de Steam nativos y bajo **Proton** (`compatdata/<appid>/pfx`), en cualquier biblioteca (incluida la microSD).
  - **Atajos no-Steam** añadidos a Steam, con su propio prefijo de Proton.
  - Juegos de **Heroic** (Epic/GOG) y **Lutris**, con sus prefijos de Wine.
  - Un **escaneo completo** de carpetas conocidas (`AppData`, `Documentos`, `~/.local/share`, `~/.config`, Flatpak...) para juegos instalados de cualquier otra forma.
  - **Emuladores**: RetroArch, Dolphin, PCSX2, DuckStation, PPSSPP, RPCS3, Cemu, Ryujinx, yuzu y sus forks, Citra, Lime3DS, Azahar, Vita3K y Xenia. Incluye las rutas nativas, las de Flatpak y, por tanto, las de EmuDeck.
  - **Juegos personalizados** con las rutas que tú indiques.
- **Ignora por defecto los juegos que ya tienen nube** en su tienda (por ejemplo Steam Cloud); se pueden incluir con una opción.
- **Copias en tu NAS por SMB2/3** sin montar nada y sin root (se usa [smbprotocol](https://github.com/jborean93/smbprotocol)), o en cualquier carpeta, incluida una unidad de red ya montada.
- **Copias portables entre sistemas.** Las rutas se guardan como `<winAppData>/Juego/save.dat`, así que una partida de Windows se restaura en la Steam Deck (Proton) y viceversa.
- **Automático:**
  - Backup al cerrar el juego.
  - Backup periódico mientras juegas.
  - Restauración de la versión más nueva del NAS al lanzar el juego (por ejemplo, si jugaste en otro PC).
- **Seguro:**
  - Historial de versiones con retención: las N últimas más una diaria durante X días. Las copias se pueden bloquear.
  - Instantánea local antes de cada restauración, con opción de deshacer.
  - Detección de conflictos cuando hay cambios en este equipo y en otro.
  - Cola local si el NAS no está disponible; se sube cuando vuelve.

## Instalación

### Steam Deck / SteamOS (Decky)

1. Instala [Decky Loader](https://decky.xyz).
2. Descarga `Synker-decky.zip` de la página de *Releases* e instálalo desde *Decky → Ajustes → Developer → Install plugin from ZIP*.
3. Abre el menú de acceso rápido (`…`), entra en **Synker → Ajustes**, elige **NAS (SMB)** y rellena el host, el recurso compartido, el usuario y la contraseña. Al pulsar **Guardar ajustes** se prueba la conexión.

Con eso basta: al lanzar un juego se restaura la versión del NAS si es más nueva, al cerrarlo se hace backup y, mientras juegas, se hacen copias cada 15 minutos.

**Modo estricto (opcional).** Las notificaciones de Steam llegan cuando el juego ya está arrancando. Si quieres que la restauración termine *antes* de que el juego empiece, añade esto en las opciones de lanzamiento del juego:

```
~/homebrew/plugins/Synker/bin/synker run --appid <APPID> -- %command%
```

El plugin muestra la línea exacta en la ficha de cada juego.

### Linux / Windows (escritorio)

Descarga `synker` y `synker-gui` (o `synker.exe` y `synker-gui.exe`) de *Releases*, o instálalo desde el código:

```bash
pip install ".[gui]"        # en Windows añade también [keyring]
```

**Interfaz gráfica:**
- `synker-gui` abre una ventana con las pestañas Juegos, Ajustes y Registro, más un icono en la bandeja que ejecuta el demonio de backups automáticos.
- Marca *Iniciar con la sesión* para que arranque al iniciar sesión.

**Línea de comandos:**

```bash
synker setup                      # asistente: NAS SMB o carpeta, usuario, contraseña
synker scan                       # juegos detectados y sus archivos
synker status                     # estado de sincronización con el NAS
synker backup --all               # backup de todo ahora
synker list "Hollow Knight"       # versiones guardadas
synker restore "Hollow Knight" --backup <id>
synker restore "Hollow Knight" --undo        # deshacer la última restauración
synker add "Mi juego" --path "<home>/MiJuego/saves" --process mijuego.exe
synker daemon install             # demonio al iniciar sesión (systemd --user / carpeta Inicio)
synker run --appid 1234 -- %command%         # envoltorio para opciones de lanzamiento
```

Todos los comandos aceptan `--json` para usarlos desde scripts.

## Estructura en el NAS

```
<recurso>/<carpeta>/synker/
  games/<juego>/index.json                 historial de copias
  games/<juego>/<fecha>-<equipo>.zip       archivos + meta.json (se puede abrir a mano)
  devices/<equipo>.json                    última versión sincronizada por cada equipo
```

## Configuración

Los ajustes están en `config.toml`, que se edita con `synker config set clave valor`. Por ejemplo:

```bash
synker config set backup.periodic_minutes 10
synker config set backup.conflict_policy keep-both   # ask | prefer-remote | prefer-local | keep-both
synker config set steam_roots /mnt/juegos/Steam
synker config set wine_prefixes ~/Games/mi-prefijo
```

La contraseña SMB se guarda en el llavero del sistema si existe y, si no (como en Decky), en un archivo `secrets.json` con permisos 0600.

## Desarrollo

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev,gui]"
.venv/bin/pytest            # tests (los de SMB necesitan SYNKER_TEST_SMB_* apuntando a un servidor)
.venv/bin/ruff check src tests
python packaging/build.py --gui          # binarios con PyInstaller en dist/
decky/scripts/package.sh                 # zip del plugin de Decky en decky/out/
```

Arquitectura:
- `src/synker/manifest`: descarga del manifest e índice compacto.
- `src/synker/detect`: Steam, Heroic, Lutris, emuladores, placeholders y escaneo.
- `src/synker/storage`: almacenamiento local y SMB.
- `src/synker/engine.py`: backup, restauración, sincronización y cola.
- `src/synker/daemon.py` y `watcher.py`: detección de juegos en ejecución.
- `src/synker/gui`: interfaz con PySide6.
- `decky/`: el plugin, con `main.py` (adaptador que llama al binario `bin/synker`) y `src/` (interfaz React del menú de acceso rápido).

## Créditos y licencia

GPL-3.0-or-later.

- La lógica de resolución de rutas está basada en [ludusavi](https://github.com/mtkennerly/ludusavi) (MIT, © Matthew T. Kennerly), y los datos de juegos vienen de su [manifest](https://github.com/mtkennerly/ludusavi-manifest), que procede de PCGamingWiki.
- El andamiaje del plugin deriva de [decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template) (BSD-3-Clause).

---

## English summary

Synker automatically backs up game saves to a NAS over SMB (or to any folder) and restores them. It is meant for games and emulators that have no cloud saves, and runs on Linux, Windows and SteamOS (as a Decky plugin).

**Detection.** Save locations are found through the ludusavi manifest. Supported sources:
- Steam, including Proton prefixes and non-Steam shortcuts
- Heroic and Lutris
- a full scan of well-known folders
- built-in emulator profiles
- custom games

**Portability.** Backups store portable placeholder paths, so a save made on Windows restores into Proton and vice versa.

**Automation.**
- The Decky plugin hooks Steam's game start/stop events.
- On desktop, a daemon watches processes. The GUI tray app runs this daemon.
- Backups run on exit and periodically while playing. Newer NAS saves are restored on launch.

**Safety.** Synker keeps version history with retention and a local snapshot before every restore (with undo). It also detects conflicts and queues backups while the NAS is offline.
