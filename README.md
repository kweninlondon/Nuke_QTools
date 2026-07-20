# Nuke QTools

A collection of Python scripts, gizmos, and utilities for Foundry Nuke.

## Repository layout

- `init.py` adds the toolkit folders to Nuke's plug-in path.
- `menu.py` builds the QTools menu in Nuke.
- `python/qtools/` contains reusable Python modules.
- `gizmos/` contains `.gizmo` files.
- `icons/` contains menu and toolbar artwork.

## Install in Nuke on macOS

Link the repository into your Nuke user folder, then install the bootstrap:

```shell
ln -s /path/to/Nuke_QTools ~/.nuke/QTools
ln -s ~/.nuke/QTools/setup/nuke_init.py ~/.nuke/init.py
```

Restart Nuke after changing startup files. A **QTools** menu will appear in the
main Nuke menu bar.

## Everyday Git workflow

1. Edit and test a tool.
2. Review changes in VS Code's Source Control panel.
3. Commit with a short description of the change.
4. Sync or push the commit to GitHub.

Do not add personal Nuke preferences, caches, renders, or sensitive production
data to this repository.
