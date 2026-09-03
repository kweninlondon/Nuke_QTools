# Nuke QTools

A collection of Python scripts, gizmos, and utilities for Foundry Nuke.

## Repository layout

- `init.py` adds the toolkit folders to Nuke's plug-in path.
- `menu.py` builds the QTools menu in Nuke.
- `python/qtools/` contains reusable Python modules.
- `gizmos/` contains reusable `.gizmo` files.
- `groups/` contains self-contained node groups pasted by QTools commands.
- `icons/` contains menu and toolbar artwork.

## Install in Nuke on macOS

Link the repository into your Nuke user folder, then install the bootstrap:

```shell
ln -s /path/to/Nuke_QTools ~/.nuke/QTools
ln -s ~/.nuke/QTools/setup/nuke_init.py ~/.nuke/init.py
```

Restart Nuke after changing startup files. A **QTools** menu will appear in the
main Nuke menu bar.

## Install on a new Windows machine

These steps install Git, create a new SSH key for GitHub, and install QTools in
your Nuke user folder. Run commands in **PowerShell** unless a step says to use
an Administrator window.

### 1. Install Git

Open PowerShell and run:

```powershell
winget install --id Git.Git -e --source winget
```

Close and reopen PowerShell, then check that Git is available:

```powershell
git --version
```

If `winget` is unavailable, download the installer from the
[official Git for Windows page](https://git-scm.com/install/windows).

### 2. Set your Git identity

Use the name and email associated with your GitHub account:

```powershell
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

### 3. Create an SSH key

Replace the example email, then accept the default file location when asked.
Adding a passphrase is recommended.

```powershell
ssh-keygen -t ed25519 -C "you@example.com"
```

Never share the private file `id_ed25519`. Only the `.pub` file is added to
GitHub.

### 4. Optional: start the Windows SSH agent

The SSH agent remembers a key's passphrase. You can skip this step and enter
the passphrase when Git asks for it.

Open **PowerShell as Administrator** and run:

```powershell
Get-Service -Name ssh-agent | Set-Service -StartupType Automatic
Start-Service ssh-agent
```

Close the Administrator window. In a normal PowerShell window, run:

```powershell
ssh-add "$env:USERPROFILE\.ssh\id_ed25519"
git config --global core.sshCommand "C:/Windows/System32/OpenSSH/ssh.exe"
```

The second command ensures Git for Windows uses the same SSH agent.

### 5. Add the public key to GitHub

Copy the public key:

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" | Set-Clipboard
```

In GitHub, open **Settings > SSH and GPG keys > New SSH key**, give the new
machine a descriptive title, keep **Authentication Key** selected, paste the
key, and click **Add SSH key**. See
[GitHub's SSH-key instructions](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account).

Test the connection:

```powershell
ssh -T git@github.com
```

Type `yes` if asked to trust GitHub's host key. A successful test says that
you authenticated successfully (GitHub does not provide shell access).

### 6. Clone and enable QTools in Nuke

Choose the exact folder where you want the repository. For a network location,
prefer its UNC path (for example `\\server\share`) because it does not depend on
a mapped drive letter. Replace the example path in this command with yours:

```powershell
git clone git@github.com:kweninlondon/Nuke_QTools.git "\\server\share\Nuke_QTools"
```

You can also use a mapped drive or a local folder, for example:

```powershell
git clone git@github.com:kweninlondon/Nuke_QTools.git "Q:\Tools\Nuke_QTools"
```

Create Nuke's user folder if necessary, then open its `init.py`:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.nuke"
notepad "$env:USERPROFILE\.nuke\init.py"
```

If Notepad asks to create the file, choose **Yes**. Add the following lines,
replacing the example with the same repository path used above. If `init.py`
already contains other setup, keep it and add these lines at the end:

```python
import nuke
nuke.pluginAddPath(r"\\server\share\Nuke_QTools")
```

For a mapped drive, use forward slashes, for example
`nuke.pluginAddPath("Q:/Tools/Nuke_QTools")`.

Restart Nuke. A **QTools** menu should appear in the main menu bar.

### Updating QTools later

```powershell
Set-Location "\\server\share\Nuke_QTools"
git pull
```

## Install CG To Film

CG To Film is bundled as `groups/CGTOFILM.nk`. Restart Nuke, then use either
**QTools > Groups > CG To Film** or **Nodes > QTools > CG To Film**.

The command pastes a Group node whose complete internal node graph is stored
in the current Nuke script. Scripts created this way do not require the
original QTools asset to reopen CG To Film correctly.

## QuickTime FPS Conform

Select one movie Read node and choose **QTools > Utilities > Conform QuickTime
FPS**. The tool reads the encoded `input/frame_rate` metadata, compares it with
the script FPS, and creates a Retime, OFlow, or Kronos node at the calculated
speed. The output start frame defaults to the Read node's first frame and can
be changed in the dialog. If a movie does not expose usable FPS metadata, enter
the source FPS manually in the dialog.

## Create AYON Writes

When Nuke is launched through AYON, select one or more native Read or Write
nodes and choose **QTools > Utilities > Create AYON Writes**. A selected Read is
used as the input of a new AYON Write. For a selected native Write, the AYON
Write is created alongside it using the same input; the original Write is kept.
QTools targets AYON's **Render (write)** creator (`create_write_render`), with
the older generic `create_write` identifier retained as a compatibility fallback.
Each preview row can instead target AYON's **Prerender (write)** creator and can
independently enable **Match frame range**. Batch buttons set the type or range
matching for all rows. Range matching copies the nearest upstream Read's first
and last frames to the created group's internal Write, enables its range limit,
and updates the group's exposed range knobs when they are available.

The preview proposes a render variant from each selected node's filename.
Choose **Edit rules** to configure ordered filename searches, which part of the
name to keep, removable masks, and optional fixed variants. **Keep Left** and
**Keep Right** exclude the matched search text; **Keep All** preserves the full
name. In a removal mask, each `#` matches one digit. A fixed variant overrides
the derived text. For example, a `roto_` rule with **Keep Right** that removes
`_v###` converts `BD2_205_010_030_plateFG01_roto_character_v001` to `Character`.

## Straighten Chain

Select at least two nodes and choose **QTools > Utilities > Straighten Chain...**
or press **Ctrl+Alt+A**. Toggle **Vertical chain** or **Horizontal chain** to
preview the selected nodes on a shared centre line. Apply records one Nuke Undo
step; toggling off, cancelling, or discarding restores the original positions.

## Teleport

Teleport shares selected nodes between artists using a common folder. Its
commands are available under **QTools > Teleport**.

Before sharing across workstations, edit
`python/qtools/teleport_settings.py` and set `SHARED_PATH` to a folder every
participating artist can read and write. Alternatively, define the
`TELEPORT_SHARED_PATH` environment variable. The default
`~/teleport_shared` location is suitable for local testing only.

- **Telecopy** saves the selected non-Viewer nodes for the current artist.
- **Telepaste** selects an artist's stored nodes and pastes them.
- **Telepaste Latest** pastes the most recently updated teleport.

Teleport transfers node definitions only. Referenced media, gizmos, fonts,
and plug-ins must also be available to the receiving artist.

## Everyday Git workflow

1. Edit and test a tool.
2. Review changes in VS Code's Source Control panel.
3. Commit with a short description of the change.
4. Sync or push the commit to GitHub.

Do not add personal Nuke preferences, caches, renders, or sensitive production
data to this repository.
