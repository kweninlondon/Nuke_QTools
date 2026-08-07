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

## Install CG To Film

CG To Film is bundled as `groups/CGTOFILM.nk`. Restart Nuke, then use either
**QTools > Groups > CG To Film** or **Nodes > QTools > CG To Film**.

The command pastes a Group node whose complete internal node graph is stored
in the current Nuke script. Scripts created this way do not require the
original QTools asset to reopen CG To Film correctly.

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
